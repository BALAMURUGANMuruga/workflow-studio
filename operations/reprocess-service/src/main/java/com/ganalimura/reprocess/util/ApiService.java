package com.ganalimura.reprocess.util;



import org.springframework.stereotype.Service;

@Service
public class ApiService {

    public String modifyOrderNo(String xml) {
    	
    	
    	
        return xml.replaceFirst("OrderNo=\"(\\d+)\"", 
                "OrderNo=\"" + System.currentTimeMillis()%100000 + "\"");
    }

    public void saveOrder(String xml) {
        System.out.println("Order Saved"+xml);
    }

    public void getOrderDetails(String orderNo) {
        System.out.println("Fetched Order: " + orderNo);
    }

    public void reprocessOrder(String txnId) {
        System.out.println("Reprocessed Order: " + txnId);
    }
}
