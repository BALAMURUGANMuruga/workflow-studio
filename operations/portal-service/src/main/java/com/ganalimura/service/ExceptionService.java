package com.ganalimura.service;

import java.io.StringReader;
import java.util.*;

import javax.xml.parsers.DocumentBuilderFactory;

import org.apache.commons.text.StringEscapeUtils;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.web.socket.WebSocketSession;
import org.w3c.dom.Document;
import org.w3c.dom.Node;
import org.xml.sax.InputSource;

import com.fasterxml.jackson.dataformat.xml.XmlMapper;
import com.ganalimura.entity.SterlingPortalClient;
import com.ganalimura.util.PortalOrderXmlParser;
import com.ganalimura.util.WebSocketUtil;
import com.ganalimura.util.XmlUtil;


@Service
public class ExceptionService {

    @Autowired
    private XmlUtil xmlUtil;

    @Autowired
    private SterlingPortalClient sterlingPortalClient;

    @Autowired
    private IntegrationErrorService integrationErrorService;
    
    @Autowired
    private WebSocketUtil webSocketUtil;
    
    @Autowired
    private ExceptionProcessor exceptionProcessor;

    private final XmlMapper xmlMapper = new XmlMapper();

    // ================= CONTROL =================
    private ProcessControl ctrl = new ProcessControl();

    class ProcessControl {
        volatile boolean paused = false;
        volatile boolean stopped = false;

        public void pause() {
            this.paused = true;
        }

        public void resume() {
            this.paused = false;
        }

        public void stop() {
            this.stopped = true;
            this.paused = false; // 🔥 important
        }
    }

    // ================= MAIN WEBSOCKET STREAM =================

    @SuppressWarnings("unchecked")
    public void startStreamWS(String errorCode, WebSocketSession session) throws Exception {

        ctrl = new ProcessControl();

        webSocketUtil.send(session, "START", null, null);

        String inputXml = xmlUtil.loadXml("xml/inbox/getIntegrationErrorList_input.xml")
                .replace("{ErrorCode}", errorCode);

        String outputXml = xmlUtil.loadXml("xml/inbox/getIntegrationErrorList_output.xml");

        Map<String, Object> response =
                sterlingPortalClient.postInterop("getIntegrationErrorList", inputXml, outputXml);

        String xml = (String) response.get("xml");

        Map<String, Object> indexarray =
                xmlMapper.readValue(xml, Map.class);

        Object listObj = indexarray.get("IntegrationError");

        if (listObj == null) {
        	webSocketUtil.send(session, "No Records Found", null, null);
            return;
        }

        List<Map<String, Object>> list =
                listObj instanceof List
                        ? (List<Map<String, Object>>) listObj
                        : Arrays.asList((Map<String, Object>) listObj);

        int count = 0;

        for (Map<String, Object> inbox : list) {

        	if (ctrl.stopped) {
        	    webSocketUtil.send(session, "⛔ Process Stopped by User", null, null);
        	    break;
        	}

            while (ctrl.paused) {
                webSocketUtil.send(session, "⏸ Paused", null, null);
                Thread.sleep(1000);
            }

            count++;
            String txnId = inbox.get("ErrorTxnId").toString();

            // STEP 1
            webSocketUtil.send(session, "Processing " + count + " - " + txnId, null, null);

            // STEP 2 → GET DETAILS
            Map<String, Object> detail =
                    integrationErrorService.getExceptionDetailsAsync(txnId).join();

            String detailXml = (String) (detail.get("xml") != null
                    ? detail.get("xml")
                    : detail.get("error"));

            if (detailXml == null) continue;

            Document doc = DocumentBuilderFactory.newInstance()
                    .newDocumentBuilder()
                    .parse(new InputSource(new StringReader(detailXml)));

            Node inputXmlNode = doc.getElementsByTagName("InputXml").item(0);
            Node errorXmlNode = doc.getElementsByTagName("ErrorXml").item(0);

            String input = inputXmlNode != null
                    ? inputXmlNode.getAttributes().getNamedItem("InputXml").getNodeValue()
                    : "";

            String error = errorXmlNode != null
                    ? errorXmlNode.getAttributes().getNamedItem("ErrorXml").getNodeValue()
                    : "";

            String decodedErrorXml = StringEscapeUtils.unescapeXml(error);

            // STEP 3 → SEND XML
            webSocketUtil.send(session, "Exception Details", input, decodedErrorXml);

            // STEP 4 → PROCESS
            Map<String, String> data =
                    PortalOrderXmlParser.extractAttributes(decodedErrorXml);
            
            String errorDescription = data.getOrDefault("ErrorDescription", "");
            
            exceptionProcessor.checkExceptionIssues(session,data, input,errorDescription,txnId,ctrl);

           

            // STEP 5 → DONE
            webSocketUtil.send(session, "Processed " + txnId, null, null);

            Thread.sleep(300);
        }

        webSocketUtil.send(session, "Completed", null, null);
    }

   


    public List<Map<String, String>> getExceptionCodes() {

        List<Map<String, String>> list = new ArrayList<>();

        list.add(create("YFS10137", "Order Validation Failed"));
        list.add(create("YFC0001", "General Failure"));
        list.add(create("YFC0801", "Inventory Issue"));
        list.add(create("YFC0051", "Payment Failure"));

        return list;
    }

    private Map<String, String> create(String code, String description) {
        Map<String, String> map = new HashMap<>();
        map.put("code", code);
        map.put("description", description);
        return map;
    }
    
    public void pause(WebSocketSession session) throws Exception {
        ctrl.pause();
        webSocketUtil.send(session, "⏸ Process Paused", null, null);
    }

    public void resume(WebSocketSession session) throws Exception {
        ctrl.resume();
        webSocketUtil.send(session, "▶ Process Resumed", null, null);
    }

    public void stop(WebSocketSession session) throws Exception {
        ctrl.stop();
        webSocketUtil.send(session, "⛔ Process Stopped", null, null);
    }
}