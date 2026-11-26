// Send configured interoperability requests to Sterling.
package com.ganalimura.workflowservice.service;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

@Service
public class SterlingInteropService {
    private static final Pattern ROOT_PATTERN = Pattern.compile("<([A-Za-z0-9_:-]+)(\\s|/|>)");
    private final RestClient client;

    @Value("${oms.interop.url:http://localhost:9080/smcfs/interop/InteropHttpServlet}")
    private String defaultUrl;
    @Value("${oms.interop.user:admin}")
    private String defaultUser;
    @Value("${oms.interop.password:password}")
    private String defaultPassword;

    public SterlingInteropService(RestClient.Builder builder) { this.client = builder.build(); }

    public Map<String, Object> postInterop(String apiName, String xmlPayload, String outputXml,
            String user, String password, String url, String serviceName) {
        Map<String, Object> result = new LinkedHashMap<>();
        String targetUrl = choose(url, defaultUrl);
        if (targetUrl == null || targetUrl.isBlank()) {
            return Map.of("success", false, "error", "Missing INTEROP_URL");
        }
        if (xmlPayload == null || xmlPayload.isBlank()) {
            return Map.of("success", false, "error", "Missing XML payload");
        }
        boolean serviceMode = serviceName != null && !serviceName.isBlank();
        String effectiveApi = choose(apiName, serviceName);
        if (effectiveApi == null) effectiveApi = "";

        MultiValueMap<String, String> form = new LinkedMultiValueMap<>();
        form.add("YFSEnvironment.progId", "SterlingHttpTester");
        form.add("YFSEnvironment.userId", choose(user, defaultUser));
        form.add("YFSEnvironment.password", choose(password, defaultPassword));
        form.add("IsFlow", serviceMode ? "Y" : "N");
        form.add("ServiceName", serviceMode ? serviceName : "");
        form.add("ApiName", effectiveApi);
        form.add("InteropApiName", effectiveApi);
        form.add("InteropApiData", xmlPayload);
        if (outputXml != null && !outputXml.isBlank()) form.add("TemplateData", outputXml);

        try {
            String raw = client.post().uri(targetUrl)
                    .contentType(MediaType.APPLICATION_FORM_URLENCODED)
                    .body(form).retrieve().body(String.class);
            return extractXml(raw == null ? "" : raw.trim());
        } catch (RestClientException ex) {
            result.put("success", false);
            result.put("exception", ex.getMessage());
            return result;
        }
    }

    private Map<String, Object> extractXml(String raw) {
        Map<String, Object> out = new LinkedHashMap<>();
        Matcher m = ROOT_PATTERN.matcher(raw);
        if (m.find()) {
            String root = m.group(1);
            String close = "</" + root + ">";
            int start = raw.indexOf("<" + root);
            if (raw.contains(close)) {
                int end = raw.lastIndexOf(close) + close.length();
                out.put("success", true); out.put("xml", raw.substring(start, end)); out.put("raw", raw);
                return out;
            }
            Matcher self = Pattern.compile("<" + Pattern.quote(root) + "[^>]*?/?>").matcher(raw);
            if (self.find()) {
                out.put("success", true); out.put("xml", self.group()); out.put("raw", raw);
                return out;
            }
        }
        out.put("success", false);
        out.put("error", raw.toLowerCase().contains("<html") || raw.contains("403")
                ? "OMS returned HTML/403 error" : "Unknown OMS response");
        out.put("raw", raw);
        return out;
    }

    private String choose(String preferred, String fallback) {
        return preferred != null && !preferred.isBlank() ? preferred : fallback;
    }
}
