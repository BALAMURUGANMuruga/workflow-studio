
package com.ganalimura.workflowservice.controller;

import com.ganalimura.workflowservice.service.AiClientService;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import java.util.Map;

@RestController
@RequestMapping("/api/ai")
public class AiController {

    private final AiClientService aiClient;

    public AiController(AiClientService aiClient) {
        this.aiClient = aiClient;
    }

    public record ChatRequest(String message) {}

    public record ChatResponse(
            boolean success,
            String answer,
            Object data,
            String source,
            String xml
    ) {}


@PostMapping("/chat")
public ResponseEntity<ChatResponse> chat(
        @RequestBody ChatRequest request,
        @RequestHeader(value = "Authorization", required = false) String authorization) {

    if (request == null
            || request.message() == null
            || request.message().isBlank()) {
        throw new ResponseStatusException(
                HttpStatus.BAD_REQUEST,
                "Message cannot be empty");
    }

    try {
        aiClient.verifyPortalSession(authorization);
    } catch (IllegalArgumentException | org.springframework.web.client.HttpClientErrorException ex) {
        throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Sign in to the Operations Portal", ex);
    } catch (org.springframework.web.client.RestClientException ex) {
        throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Portal authentication is unavailable", ex);
    }

    try {
        // Preserve both the answer and mode from Python.
        com.ganalimura.workflowservice.service.AiClientService.ChatResponse aiResponse =
                aiClient.askAiDetailed(request.message());

        return ResponseEntity.ok(new ChatResponse(
                true,
                aiResponse.response(),
                null,
                aiResponse.mode() != null
                        ? aiResponse.mode()
                        : "python-ai",
                null
        ));

    } catch (Exception ex) {
        throw new ResponseStatusException(
                HttpStatus.BAD_GATEWAY,
                "Python AI request failed",
                ex
        );
    }
}

}
