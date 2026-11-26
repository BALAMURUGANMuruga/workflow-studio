package com.ganalimura.service;

import java.util.Map;
import java.util.concurrent.CompletableFuture;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;

import com.ganalimura.entity.SterlingPortalClient;
import com.ganalimura.util.XmlUtil;



@Service
public class IntegrationErrorService {

    private static final Logger log = LoggerFactory.getLogger(IntegrationErrorService.class);

    @Autowired
    private XmlUtil xmlUtil;

    @Autowired
    private SterlingPortalClient sterlingPortalClient;

    // ================= SAVE ERROR =================
    @Async
    public CompletableFuture<Map<String, Object>> saveIntegrationErrorAsync(String errorTxnId, String inputXmlMap) {
        try {
            log.info("Async SAVE start txnId={}", errorTxnId,inputXmlMap);
            

            String inputXml = xmlUtil
                    .loadXml("xml/order/saveIntegrationError-input.xml")
                    .replace("{errorTxnId}", errorTxnId)
                    .replace("{inputXml}", inputXmlMap);
            
            System.out.print("Async SAVE "+inputXml);

            Map<String, Object> response =
                    sterlingPortalClient.postInterop("saveIntegrationError", inputXml, "");

            log.info("Async SAVE completed txnId={}", errorTxnId);

            return CompletableFuture.completedFuture(response);

        } catch (Exception e) {
            log.error("Async SAVE failed txnId={}", errorTxnId, e);
            return CompletableFuture.failedFuture(e);
        }
    }

    // ================= GET DETAILS =================
    @Async
    public CompletableFuture<Map<String, Object>> getExceptionDetailsAsync(String errorTxnId) {
        try {
            log.info("Async GET DETAILS start txnId={}", errorTxnId);

            String inputXml = xmlUtil
                    .loadXml("xml/inbox/getIntegrationErrorDetails_input.xml")
                    .replace("{errorTxnId}", errorTxnId)
                    .replace("{ignoreOrdering}", "Y");

            Map<String, Object> response =
                    sterlingPortalClient.postInterop("getIntegrationErrorDetails", inputXml, "");

            log.info("Async GET DETAILS completed txnId={}", errorTxnId);

            return CompletableFuture.completedFuture(response);

        } catch (Exception e) {
            log.error("Async GET DETAILS failed txnId={}", errorTxnId, e);
            return CompletableFuture.failedFuture(e);
        }
    }

    // ================= REPROCESS =================
    @Async
    public CompletableFuture<Map<String, Object>> reprocessExceptionAsync(String errorTxnId, String reprocessXml) {
        try {
            log.info("Async REPROCESS start txnId={}", errorTxnId);

            String inputXml = xmlUtil
                    .loadXml("xml/reprocess/reprocessIntegrationError_input.xml")
                    .replace("{errorTxnId}", errorTxnId)
                    .replace("{inputXml}", reprocessXml);

            Map<String, Object> response =
                    sterlingPortalClient.postInterop("reprocessIntegrationError", inputXml, "");

            log.info("Async REPROCESS completed txnId={}", errorTxnId);

            return CompletableFuture.completedFuture(response);

        } catch (Exception e) {
            log.error("Async REPROCESS failed txnId={}", errorTxnId, e);
            return CompletableFuture.failedFuture(e);
        }
    }

    // ================= IGNORE =================
    @Async
    public CompletableFuture<Map<String, Object>> ignoreExceptionAsync(String errorTxnId) {
        try {
            log.info("Async IGNORE start txnId={}", errorTxnId);

            String inputXml = xmlUtil
                    .loadXml("xml/order/ignoreIntegrationError_input.xml")
                    .replace("{errorTxnId}", errorTxnId);

            Map<String, Object> response =
                    sterlingPortalClient.postInterop("ignoreIntegrationError", inputXml, "");

            log.info("Async IGNORE completed txnId={}", errorTxnId);

            return CompletableFuture.completedFuture(response);

        } catch (Exception e) {
            log.error("Async IGNORE failed txnId={}", errorTxnId, e);
            return CompletableFuture.failedFuture(e);
        }
    }

    // ================= SYNC WRAPPERS =================

    public Map<String, Object> saveIntegrationError(String errorTxnId, String inputXmlMap) {
        return saveIntegrationErrorAsync(errorTxnId, inputXmlMap).join();
    }

    public Map<String, Object> getExceptionDetails(String errorTxnId) {
        return getExceptionDetailsAsync(errorTxnId).join();
    }

    public Map<String, Object> reprocessException(String errorTxnId, String reprocessXml) {
        return reprocessExceptionAsync(errorTxnId, reprocessXml).join();
    }

    // ================= ORDER DETAILS =================
    @Async
    public CompletableFuture<Map<String, Object>> getOrderDetailsAsync(Map<String, String> values) {
        try {

            if (values == null || values.isEmpty()) {
                log.warn("Async getOrderDetails called with empty values");
                return CompletableFuture.completedFuture(null);
            }

            String enterpriseCode = values.getOrDefault("EnterpriseCode", "");
            String documentType = values.getOrDefault("DocumentType", "");
            String orderNo = values.getOrDefault("orderNo",
                    values.getOrDefault("OrderNo", ""));

            log.info("Async ORDER DETAILS start with values: {}", values);
            log.info("Calling getOrderDetails API for OrderNo={}, DocumentType={}, EnterpriseCode={}",
                    orderNo, documentType, enterpriseCode);

            String inputXml = xmlUtil
                    .loadXml("xml/order/getOrderDetails_input.xml")
                    .replace("{EnterpriseCode}", enterpriseCode)
                    .replace("{DocumentType}", documentType)
                    .replace("{OrderNo}", orderNo);

            String outputXml = xmlUtil
                    .loadXml("xml/order/getOrderDetails_output.xml");

            Map<String, Object> response =
                    sterlingPortalClient.postInterop("getOrderDetails", inputXml, outputXml);

            log.info("Async ORDER DETAILS completed OrderNo={}", orderNo);

            return CompletableFuture.completedFuture(response);

        } catch (Exception e) {
            log.error("Async ORDER DETAILS failed", e);
            return CompletableFuture.failedFuture(e);
        }
    }
}