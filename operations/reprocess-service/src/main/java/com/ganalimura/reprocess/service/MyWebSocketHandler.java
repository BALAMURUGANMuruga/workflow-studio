package com.ganalimura.reprocess.service;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.handler.TextWebSocketHandler;

@Component
public class MyWebSocketHandler extends TextWebSocketHandler {

    @Autowired
    private ExceptionService exceptionService;

    @Override
    public void handleTextMessage(WebSocketSession session, TextMessage message) throws Exception {

        String errorCode = message.getPayload();

        // start streaming
        exceptionService.startStreamWS(errorCode, session);
    }
}
