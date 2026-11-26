package com.ganalimura.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.socket.WebSocketSession;

import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

@Service
public class ExceptionHandlerService {

    private static final Logger log = LoggerFactory.getLogger(ExceptionHandlerService.class);

    private final IntegrationErrorService integrationErrorService;

    public ExceptionHandlerService(IntegrationErrorService integrationErrorService) {
        this.integrationErrorService = integrationErrorService;
    }

    // ================= MAIN PROCESS =================
    public void processException(WebSocketSession session,Map<String, String> data,
                                 String input,
                                 String errorTxnId) {

        if (data == null) {
            log.warn("No data found for txnId: {}", errorTxnId);
            return;
        }

        ActionType action = checkExceptionIssues(session,data, input);

        switch (action) {

            case IGNORE:
                log.info("Ignoring exception for txnId: {}", errorTxnId);

                // Optional: call OMS ignore API
                // integrationErrorService.ignoreException(errorTxnId);

                break;

            case SAVE:
                handleSave(errorTxnId, input);
                break;

            case REPROCESS:
                handleReprocess(errorTxnId, input);
                break;

            case NONE:
            default:
                log.warn("No action taken for txnId: {}", errorTxnId);
                break;
        }
    }

    // ================= SAVE =================
    private void handleSave(String errorTxnId, String input) {

        try {
            String encodedXml = encodeXml(input);

            Map<String, Object> saveResponse =
                    integrationErrorService.saveIntegrationError(errorTxnId, encodedXml);

            log.info("Save response for txnId {}: {}", errorTxnId, saveResponse);

            if (Boolean.TRUE.equals(saveResponse.get("success"))) {

                Map<String, Object> details =
                        integrationErrorService.getExceptionDetails(errorTxnId);

                log.info("Fetched details after save: {}", details);
            }

        } catch (Exception e) {
            log.error("Error during SAVE for txnId: {}", errorTxnId, e);
        }
    }

    // ================= REPROCESS =================
    private void handleReprocess(String errorTxnId, String input) {

        try {
            String encodedXml = encodeXml(input);

            Map<String, Object> response =
                    integrationErrorService.reprocessException(errorTxnId, encodedXml);

            log.info("Reprocess response for txnId {}: {}", errorTxnId, response);

        } catch (Exception e) {
            log.error("Error during REPROCESS for txnId: {}", errorTxnId, e);
        }
    }
    
    
   


    // ================= DECISION LOGIC =================
    private ActionType checkExceptionIssues(WebSocketSession session,Map<String, String> data, String input) {

        String modificationType = data.getOrDefault("ModificationType", "");
        String errorDescription = data.getOrDefault("ErrorDescription", "");

        // Case 1: Record already exists
        if ("Record already exists in the database.".equals(errorDescription)) {

            input = modifyOrderNo(input);

            log.info("Modified Input XML: {}", input);

            responseMessageToChat("Record already exists, ignoring exception.");

            return ActionType.IGNORE;
        }

        // Case 2: Order cannot be modified
        if ("YFS: Order cannot be modified in current status".equals(errorDescription)
                && "BACK_ORDER is disallowed because none of the statuses are set to 'allow'"
                .equals(modificationType)) {

            return ActionType.REPROCESS;
        }

        return ActionType.NONE;
    }

    // ================= HELPERS =================

    public String modifyOrderNo(String input) {
    	
    	
    	if (input == null) return null;

    	Pattern pattern = Pattern.compile("OrderNo=\"(\\d+)\"");
    	Matcher matcher = pattern.matcher(input);

    	if (matcher.find()) {
    	    System.out.println("Old OrderNo: " + matcher.group(1));
    	}

    	// ✅ FIX: assign result
    	input = input.replaceAll(
    	        "(OrderNo=\"\\d+)(\\d{2}\")",
    	        "$186\""
    	);

    	Pattern newpattern = Pattern.compile("OrderNo=\"(\\d+)\"");
    	Matcher newmatcher = newpattern.matcher(input);

    	if (newmatcher.find()) {
    	    System.out.println("New OrderNo: " + newmatcher.group(1));
    	}
        
        
        return input;
    }

    public String encodeXml(String input) {
        if (input == null) return "";
        return input
                .replace("\"", "&quot;")
                .replace("<", "&lt;")
                .replace(">", "&gt;");
    }

    private void responseMessageToChat(String message) {
        log.info("Chat Message: {}", message);
        // 🔥 Future: send to WebSocket UI if needed
    }
}