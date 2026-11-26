package com.ganalimura.service;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.web.socket.WebSocketSession;
import org.w3c.dom.Document;
import org.w3c.dom.Node;
import org.xml.sax.InputSource;

import com.fasterxml.jackson.dataformat.xml.XmlMapper;
import com.ganalimura.config.ErrorConfigLoader;
import com.ganalimura.service.ExceptionService.ProcessControl;
import com.ganalimura.util.PortalOrderXmlParser;
import com.ganalimura.util.WebSocketUtil;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.ByteArrayInputStream;
import java.io.StringReader;
import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.stream.Collectors;

import javax.xml.parsers.DocumentBuilder;
import javax.xml.parsers.DocumentBuilderFactory;

@Service
@SuppressWarnings("unchecked")
public class ExceptionProcessor {

	private static final Logger log = LoggerFactory.getLogger(ExceptionProcessor.class);

	@Autowired
	private ErrorConfigLoader configLoader;

	@Autowired
	private XmlPathExtractor extractor;

	

	@Autowired
	private IntegrationErrorService integrationErrorService;

	@Autowired
	private ExceptionHandlerService exceptionHandlerService;

	@Autowired
	private WebSocketUtil webSocketUtil;
	


	private final XmlMapper xmlMapper = new XmlMapper();

	public ActionType checkExceptionIssues(WebSocketSession session, Map<String, String> data, String inputXml,
			String errorDescription, String txnId,ProcessControl ctrl) throws Exception {

		String errorCode = data.get("ErrorCode");
		if (errorCode == null)
			return ActionType.NONE;

		Map<String, List<Map<String, Object>>> config = configLoader.getConfig();
		List<Map<String, Object>> errorScenarios = config.get(errorCode);

		if (errorScenarios == null || errorScenarios.isEmpty()) {
			return ActionType.NONE;
		}

		String root = getRootElement(inputXml);
		log.info("Root Element: {}", root);

		for (Map<String, Object> scenarioGroup : errorScenarios) {

			String expectedDesc = String.valueOf(scenarioGroup.get("errorDescription"));

			if (expectedDesc.isBlank() || !errorDescription.toLowerCase().contains(expectedDesc.toLowerCase())) {
				continue;
			}

			List<Map<String, Object>> subScenarios = (List<Map<String, Object>>) scenarioGroup.get("scenarios");

			if (subScenarios == null)
				continue;

			List<Map<String, Object>> matchingScenarios = subScenarios.stream().filter(s -> root.equals(s.get("root")))
					.collect(Collectors.toList());

			for (Map<String, Object> scenario : matchingScenarios) {

				log.info("Matched Scenario: {}", scenario.get("root"));

				List<Map<String, String>> extractedValues = extractInitialValues(scenario, inputXml);

				log.info("extractedValues: {}", extractedValues);
				log.info("apiSequence: {}", scenario.get("apiSequence"));

				for (Map<String, String> values : extractedValues) {

				    log.info("Processing values: {}", values);

				    String workingXml = inputXml;

				    List<String> sequence = (List<String>) scenario.get("apiSequence");

				    if (sequence != null && !sequence.isEmpty()) {

				        executeStepsPipeline(
				                session,
				                sequence,
				                values,
				                workingXml,
				                txnId,
				                ctrl
				        ).thenAccept(finalXml -> {

				            try {

				                // ✅ Now safe (pipeline completed)
				                List<Map<String, String>> finalValues =
				                        extractFinalValues(scenario, finalXml, inputXml);

				                for (Map<String, String> val : finalValues) {

				                    if (!evaluateConditions(scenario, val)) {
				                        log.debug("Condition failed for {}", val);
				                        continue;
				                    }

				                    String message = buildTemplate(scenario, val);
				                    log.info("Final Message: {}", message);
				                }

				            } catch (Exception e) {
				                log.error("Post-processing failed", e);
				            }

				        }).exceptionally(ex -> {
				            log.error("Pipeline failed", ex);
				            return null;
				        });
				    }
				}

				String action = String.valueOf(scenario.get("action")).replace(" ", "_");

				return ActionType.valueOf(action);
			}
		}

		return ActionType.NONE;
	}

	// ================= ASYNC API EXECUTION =================

	private String executeApiSequenceAsync(WebSocketSession session, List<String> steps, Map<String, String> values,
			String workingXml, String txnId,ProcessControl ctrl) throws Exception {

		String encodedXml = null;

		for (String step : steps) {

			// 🔴 STOP check (highest priority)
		    if (ctrl.stopped) {
		        webSocketUtil.send(session, "⛔ Process Stopped", "", "");
		        break;
		    }

		    // ⏸ PAUSE check
		    while (ctrl.paused) {
		        webSocketUtil.send(session, "⏸ Paused", "", "");
		        Thread.sleep(1000);
		    }

		    log.info("Executing step: {}", step);
		    webSocketUtil.send(session, "▶ Executing Step: " + step, "", "");

			switch (step) {

			case "GET_ORDER_DETAILS":

				log.info("Calling GET_ORDER_DETAILS with values: {}", values);
				CompletableFuture<Map<String, Object>> orderFuture = integrationErrorService
						.getOrderDetailsAsync(values);

				Map<String, Object> orderResponse = orderFuture.join();

				log.info("GET_ORDER_DETAILS response: {}", orderResponse);
				if (orderResponse != null) {
					String xml = (String) orderResponse.get("xml");
					if (xml != null && !xml.isEmpty()) {
						workingXml = xml;
					}
				}
				break;

			case "MODIFY_ORDERNO":
				workingXml = exceptionHandlerService.modifyOrderNo(workingXml);
				webSocketUtil.send(session, "Exception Modified Successfully", "", "");
				break;

			case "SAVE_ORDER":
				System.out.print("workingXml  :" + workingXml);
				encodedXml = exceptionHandlerService.encodeXml(workingXml);
				System.out.print("encodedXml  :" + encodedXml);
				log.debug("Encoded XML: {}", encodedXml);
				CompletableFuture<Map<String, Object>> ordersave = integrationErrorService
						.saveIntegrationErrorAsync(txnId, encodedXml);
				webSocketUtil.send(session, "Exception Saved Successfully", "", "");
				break;

			case "REPROCESS_ORDER":
				if (encodedXml == null || encodedXml.isEmpty()) {
					encodedXml = exceptionHandlerService.encodeXml(workingXml);
					log.debug("Generated encoded XML for REPROCESS_ORDER: {}", encodedXml);
				}

				log.info("Calling REPROCESS_ORDER with txnId={} and encoded XML", txnId);
				CompletableFuture<Map<String, Object>> reprocessFuture = integrationErrorService
						.getExceptionDetailsAsync(txnId);

				log.info("REPROCESS_ORDER reprocessFuture: {}", reprocessFuture);
				Map<String, Object> reprocessResponse = reprocessFuture.join();
				log.info("REPROCESS_ORDER response: {}", reprocessResponse);

				// Extract State and ErrorTxnId from History/IntegrationError where
				// State="Modified"
				// ✅ Fix: handle both xml & error
				String reprocessXml = (String) (reprocessResponse.get("error") != null ? reprocessResponse.get("error")
						: "");
				log.info("reprocessXml response: {}", reprocessXml);
				if (reprocessXml != null && !reprocessXml.isEmpty()) {
					try {

						log.info("========== REPROCESS XML START ==========");
						log.info("Full XML:\n{}", reprocessXml);

						// ✅ Root values
						String rootState = extractor.extractValue(reprocessXml, "/IntegrationError/@State");

						String rootErrorTxnId = extractor.extractValue(reprocessXml, "/IntegrationError/@ErrorTxnId");

						log.info("ROOT → State: {}, ErrorTxnId: {}", rootState, rootErrorTxnId);

						// ✅ History values (ALL entries)
						List<Map<String, String>> historyList = extractor.extractMultipleValues(reprocessXml,
								Map.of("state", "//History/IntegrationError/@State", "errorTxnId",
										"//History/IntegrationError/@ErrorTxnId"));

						log.info("HISTORY SIZE: {}", historyList.size());

						for (int i = 0; i < historyList.size(); i++) {
							log.info("History [{}] → {}", i, historyList.get(i));
						}

						// ✅ Try Modified from History
						String modifiedTxnId = extractor.extractValue(reprocessXml,
								"//History/IntegrationError[@State='Saved']/@ErrorTxnId");

						log.info("Modified History ErrorTxnId: {}", modifiedTxnId);

						log.info("Modified History ErrorTxnId: {}", modifiedTxnId);

						// ✅ Call async API
						Map<String, Object> detail = integrationErrorService.getExceptionDetailsAsync(modifiedTxnId)
								.join();

						// ✅ Handle xml/error safely
						String detailXml = (String) (detail.get("xml") != null ? detail.get("xml")
								: detail.get("error"));

						// ✅ Parse XML
						Document doc = DocumentBuilderFactory.newInstance().newDocumentBuilder()
								.parse(new InputSource(new StringReader(detailXml)));

						// ✅ Extract InputXml safely
						Node inputXmlNode = doc.getElementsByTagName("InputXml").item(0);

						String input = "";

						if (inputXmlNode != null && inputXmlNode.getAttributes() != null
								&& inputXmlNode.getAttributes().getNamedItem("InputXml") != null) {

							input = inputXmlNode.getAttributes().getNamedItem("InputXml").getNodeValue();
							webSocketUtil.send(session, "Fetching Exception Details Before Reprocess", input, "");

							encodedXml = exceptionHandlerService.encodeXml(input);
							integrationErrorService.reprocessExceptionAsync(modifiedTxnId, encodedXml);
							webSocketUtil.send(session, "Exception Reprocessed Successfully", "", "");
						}

						// ✅ Proper logging
						log.info("========== INPUT XML START ==========");
						log.info("Input XML (raw): {}", input);
						log.info("========== INPUT XML END ==========");

					} catch (Exception e) {
						log.error("Debug extraction failed", e);
					}
				}
				break;
			}
		}

		return workingXml;
	}

	// ================= HELPER METHODS =================

	private String getRootElement(String xml) throws Exception {
		DocumentBuilder builder = DocumentBuilderFactory.newInstance().newDocumentBuilder();

		Document doc = builder.parse(new ByteArrayInputStream(xml.getBytes()));
		return doc.getDocumentElement().getTagName();
	}

	private List<Map<String, String>> extractInitialValues(Map<String, Object> scenario, String inputXml) {

		String root = (String) scenario.get("root");

		if ("Order".equals(root)) {
			Map<String, String> values = new HashMap<>();

			String orderNo = PortalOrderXmlParser.extractOrderNo(inputXml);
			if (orderNo != null) {
				values.put("orderNo", orderNo);
			}

			Map<String, String> paths = (Map<String, String>) scenario.get("getValue");

			if (paths != null && !paths.isEmpty()) {
				List<Map<String, String>> extracted = extractor.extractMultipleValues(inputXml, paths);

				if (!extracted.isEmpty()) {
					values.putAll(extracted.get(0));
				}
			}

			return List.of(values);
		}

		Map<String, String> paths = (Map<String, String>) scenario.get("getValue");

		if (paths == null || paths.isEmpty()) {
			return List.of(new HashMap<>());
		}

		return extractor.extractMultipleValues(inputXml, paths);
	}

	private List<Map<String, String>> extractFinalValues(Map<String, Object> scenario, String workingXml,
			String inputXml) {

		Map<String, String> paths = (Map<String, String>) scenario.get("paths");

		if (paths == null || paths.isEmpty()) {
			return List.of(new HashMap<>());
		}

		if (scenario.containsKey("apiSequence") && workingXml != null) {
			return extractor.extractMultipleValues(workingXml, paths);
		}

		return extractor.extractMultipleValues(inputXml, paths);
	}

	private String buildTemplate(Map<String, Object> scenario, Map<String, String> values) {

		String template = String.valueOf(scenario.get("messageTemplate"));

		for (Map.Entry<String, String> entry : values.entrySet()) {
			String replacement = entry.getValue() == null ? "" : entry.getValue();
			template = template.replace("${" + entry.getKey() + "}", replacement);
		}

		return template;
	}

	// ================= CONDITIONS =================

	private boolean checkCondition(String op, String actual, String expected) {
		try {
			if (actual == null)
				actual = "";
			if (expected == null)
				expected = "";

			switch (op) {
			case "EQUALS":
				return actual.equals(expected);
			case "NOTEQUALS":
				return !actual.equals(expected);
			case "CONTAINS":
				return actual.contains(expected);
			case "GREATER_THAN":
				return Double.parseDouble(actual) > Double.parseDouble(expected);
			case "LESS_THAN":
				return Double.parseDouble(actual) < Double.parseDouble(expected);
			default:
				return false;
			}
		} catch (Exception e) {
			log.error("Condition check failed", e);
			return false;
		}
	}

	private boolean evaluateConditions(Map<String, Object> scenario, Map<String, String> values) {

		if (!scenario.containsKey("conditions"))
			return true;

		Map<String, Object> conditions = (Map<String, Object>) scenario.get("conditions");

		String operator = (String) conditions.getOrDefault("operator", "AND");

		List<Map<String, String>> rules = (List<Map<String, String>>) conditions.get("rules");

		boolean result = operator.equals("AND");

		for (Map<String, String> rule : rules) {

			String actual = values.getOrDefault(rule.get("field"), "");
			boolean condition = checkCondition(rule.get("operator"), actual, rule.get("value"));

			if ("AND".equals(operator)) {
				result &= condition;
				if (!result)
					break;
			} else {
				result |= condition;
				if (result)
					break;
			}
		}

		return result;
	}
	
	public CompletableFuture<String> executeStepsPipeline(
	        WebSocketSession session,
	        List<String> steps,
	        Map<String, String> values,
	        String inputXml,
	        String txnId,
	        ProcessControl ctrl) {

	    CompletableFuture<String> pipeline = CompletableFuture.completedFuture(inputXml);

	    for (String step : steps) {

	        pipeline = pipeline.thenCompose(workingXml -> {

	            return CompletableFuture.supplyAsync(() -> {

	                try {
						checkPauseStop(session, ctrl);
					} catch (Exception e) {
						// TODO Auto-generated catch block
						e.printStackTrace();
					} // 🔥 real-time control

	                log.info("▶ Executing step: {}", step);
	                try {
						webSocketUtil.send(session, "▶ Executing Step: " + step, "", "");
					} catch (Exception e) {
						// TODO Auto-generated catch block
						e.printStackTrace();
					}

	                return workingXml;

	            }).thenCompose(xml -> executeStep(step, session, values, xml, txnId, ctrl));

	        });
	    }

	    return pipeline;
	}
	
	private CompletableFuture<String> executeStep(
	        String step,
	        WebSocketSession session,
	        Map<String, String> values,
	        String workingXml,
	        String txnId,
	        ProcessControl ctrl) {

	    switch (step) {

	        case "GET_ORDER_DETAILS":

	            return integrationErrorService.getOrderDetailsAsync(values)
	                    .thenApply(response -> {

	                        try {
								checkPauseStop(session, ctrl);
							} catch (Exception e) {
								// TODO Auto-generated catch block
								e.printStackTrace();
							}

	                        String xml = (String) response.get("xml");

	                        try {
								webSocketUtil.send(session,
								        "Order Details Fetched",
								        "",
								        "");
							} catch (Exception e) {
								// TODO Auto-generated catch block
								e.printStackTrace();
							}

	                        return (xml != null && !xml.isEmpty()) ? xml : workingXml;
	                    });

	        case "MODIFY_ORDERNO":

	            return CompletableFuture.supplyAsync(() -> {

	                try {
						checkPauseStop(session, ctrl);
					} catch (Exception e) {
						// TODO Auto-generated catch block
						e.printStackTrace();
					}

	                String updated = exceptionHandlerService.modifyOrderNo(workingXml);

	                try {
						webSocketUtil.send(session,
						        "Exception Modified Successfully",
						        "",
						        "");
					} catch (Exception e) {
						// TODO Auto-generated catch block
						e.printStackTrace();
					}

	                return updated;
	            });

	        case "SAVE_ORDER":

	            return CompletableFuture.supplyAsync(() -> {

	                try {
						checkPauseStop(session, ctrl);
					} catch (Exception e) {
						// TODO Auto-generated catch block
						e.printStackTrace();
					}

	                String encoded = exceptionHandlerService.encodeXml(workingXml);

	                integrationErrorService.saveIntegrationErrorAsync(txnId, encoded);

	                try {
						webSocketUtil.send(session,
						        "Exception Saved Successfully",
						        "",
						        "");
					} catch (Exception e) {
						// TODO Auto-generated catch block
						e.printStackTrace();
					}

	                return workingXml;
	            });

	        case "REPROCESS_ORDER":

	            return integrationErrorService.getExceptionDetailsAsync(txnId)
	                    .thenCompose(response -> {

	                        try {
								checkPauseStop(session, ctrl);
							} catch (Exception e) {
								// TODO Auto-generated catch block
								e.printStackTrace();
							}

	                        String reprocessXml = (String) response.get("error");

	                        String modifiedTxnId = extractor.extractValue(
	                                reprocessXml,
	                                "//History/IntegrationError[last()]/@ErrorTxnId"
	                        );

	                        try {
								webSocketUtil.send(session,
								        "Fetching Exception Details Before Reprocess",
								        "",
								        "");
							} catch (Exception e) {
								// TODO Auto-generated catch block
								e.printStackTrace();
							}

	                        return integrationErrorService
	                                .getExceptionDetailsAsync(modifiedTxnId);

	                    })
	                    .thenApply(detail -> {

	                        try {
								checkPauseStop(session, ctrl);
							} catch (Exception e) {
								// TODO Auto-generated catch block
								e.printStackTrace();
							}

	                        String detailXml = (String) (
	                                detail.get("xml") != null
	                                        ? detail.get("xml")
	                                        : detail.get("error")
	                        );

	                        String input = extractInputXml(detailXml);

	                        try {
								webSocketUtil.send(session,
								        "Exception Details Before Reprocess",
								        input,
								        "");
							} catch (Exception e) {
								// TODO Auto-generated catch block
								e.printStackTrace();
							}

	                        String encoded = exceptionHandlerService.encodeXml(input);

	                        integrationErrorService
	                                .reprocessExceptionAsync(txnId, encoded);

	                        try {
								webSocketUtil.send(session,
								        "Exception Reprocessed Successfully",
								        "",
								        "");
							} catch (Exception e) {
								// TODO Auto-generated catch block
								e.printStackTrace();
							}

	                        return workingXml;
	                    });

	        default:
	            return CompletableFuture.completedFuture(workingXml);
	    }
	}
	
	private String extractInputXml(String detailXml) {
	    try {
	        Document doc = DocumentBuilderFactory.newInstance()
	                .newDocumentBuilder()
	                .parse(new InputSource(new StringReader(detailXml)));

	        Node node = doc.getElementsByTagName("InputXml").item(0);

	        if (node != null &&
	                node.getAttributes() != null &&
	                node.getAttributes().getNamedItem("InputXml") != null) {

	            return node.getAttributes()
	                    .getNamedItem("InputXml")
	                    .getNodeValue();
	        }

	    } catch (Exception e) {
	        log.error("XML parse failed", e);
	    }
	    return "";
	}
	
	private void checkPauseStop(WebSocketSession session, ProcessControl ctrl) throws Exception {

	    if (ctrl.stopped) {
	        webSocketUtil.send(session, "⛔ Stopped", "", "");
	        throw new RuntimeException("Stopped");
	    }

	    while (ctrl.paused) {
	        try {
	            webSocketUtil.send(session, "⏸ Paused", "", "");
	            Thread.sleep(200);
	        } catch (InterruptedException e) {
	            Thread.currentThread().interrupt();
	        }
	    }
	}
}