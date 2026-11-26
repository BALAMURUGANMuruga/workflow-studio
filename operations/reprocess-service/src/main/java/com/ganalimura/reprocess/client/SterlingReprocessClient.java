// Send exception reprocessing requests to Sterling.
package com.ganalimura.reprocess.client;

import java.util.HashMap;
import java.util.Map;

import org.springframework.stereotype.Component;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.RestTemplate;


@Component
public class SterlingReprocessClient {

    private final String INTEROP_URL = System.getenv("OMS_INTEROP_URL");
    private final String USER = System.getenv("OMS_INTEROP_USER");
    private final String PASSWORD = System.getenv("OMS_INTEROP_PASSWORD");

    public Map<String, Object> postInterop(String apiName, String xmlPayload, String outputXml) {

      
        Map<String, Object> result = new HashMap<>();

        if (INTEROP_URL == null || USER == null || PASSWORD == null) {
            return Map.of("success", false, "error", "Interop configuration is missing");
        }

        try {
            RestTemplate restTemplate = new RestTemplate();

            MultiValueMap<String, String> data = new LinkedMultiValueMap<>();
            data.add("YFSEnvironment.progId", "SterlingHttpTester");
            data.add("InteropApiName", apiName);
            data.add("IsFlow", "N");
            data.add("ServiceName", "");
            data.add("ApiName", apiName);
            data.add("YFSEnvironment.userId", USER);
            data.add("YFSEnvironment.password", PASSWORD);
            data.add("InteropApiData", xmlPayload);

            if (outputXml != null) {
                data.add("TemplateData", outputXml);
            }

            String response = restTemplate.postForObject(INTEROP_URL, data, String.class);

            System.out.println("OMS Response: " + response);

            // 🔍 Detect XML
            if (response.contains("<Errors") || response.contains("<Error")) {
                result.put("success", false);
                result.put("error", response);
            } else if (response.contains("<")) {
                result.put("success", true);
                result.put("xml", response);
            } else {
                result.put("success", false);
                result.put("error", "Unknown response");
            }

        } catch (Exception e) {
            result.put("success", false);
            result.put("exception", e.getMessage());
        }

        return result;
    }
}