// Send AI requests to the Python backend and relay the service response.

package com.ganalimura.workflowservice.service;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

@Service
public class AiClientService {

    private final RestClient client;
    private final RestClient portal;

    public AiClientService(
            RestClient.Builder builder,
            @Value("${ai.service.base-url:http://127.0.0.1:8000}") String baseUrl,
            @Value("${WORKFLOW_BRIDGE_TOKEN:}") String bridgeToken,
            @Value("${operations.portal.base-url:http://127.0.0.1:9002}") String portalUrl) {
        this.portal = builder.clone().baseUrl(portalUrl).build();
        this.client = builder.baseUrl(baseUrl)
                .defaultHeader("X-Workflow-Bridge-Token", bridgeToken)
                .build();
    }

    public void verifyPortalSession(String authorization) {
        if (authorization == null || !authorization.startsWith("Bearer ")) {
            throw new IllegalArgumentException("Missing portal session");
        }
        portal.get().uri("/api/auth/me").header("Authorization", authorization)
                .retrieve().toBodilessEntity();
    }

    // Backward-compatible method for existing callers.
    public String askAi(String message) {
        return askAiDetailed(message).response();
    }

    // Returns both the answer and the Python processing mode.
    public ChatResponse askAiDetailed(String message) {
        if (message == null || message.isBlank()) {
            throw new IllegalArgumentException(
                    "AI message must not be empty");
        }

        try {
            ChatResponse response = client.post()
                    .uri("/api/local-ai/answer")
                    .contentType(MediaType.APPLICATION_JSON)
                    .accept(MediaType.APPLICATION_JSON)
                    .body(new ChatRequest(message))
                    .retrieve()
                    .body(ChatResponse.class);

            if (response == null || response.response() == null) {
                throw new IllegalStateException(
                        "Python AI returned an empty response");
            }

            return response;

        } catch (RestClientException ex) {
            throw new IllegalStateException(
                    "Cannot call Python AI at the configured service URL. "
                    + "Check that Workflow Studio FastAPI is running.",
                    ex);
        }
    }

    public record ChatRequest(String message) {}

    public record ChatResponse(String response, String mode) {}
}
