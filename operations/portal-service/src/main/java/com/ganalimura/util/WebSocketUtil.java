package com.ganalimura.util;


import java.util.HashMap;
import java.util.Map;

import org.springframework.stereotype.Component;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;

import com.fasterxml.jackson.databind.ObjectMapper;

@Component
public class WebSocketUtil {

    private final ObjectMapper objectMapper = new ObjectMapper();

    public void send(WebSocketSession session,
                     String msg,
                     String input,
                     String error) throws Exception {

        Map<String, Object> map = new HashMap<>();
        map.put("message", msg);
        map.put("inputXml", input);
        map.put("errorXml", error);

        String json = objectMapper.writeValueAsString(map);

        session.sendMessage(new TextMessage(json));
    }
}