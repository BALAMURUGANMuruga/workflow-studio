package com.ganalimura.util;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.dataformat.xml.XmlMapper;

import org.apache.commons.text.StringEscapeUtils;
import org.springframework.stereotype.Component;


@Component
public class XmlHelper {

    private final XmlMapper xmlMapper = new XmlMapper();

    // ✅ Decode + Parse
    public JsonNode parseXml(String encodedXml) throws Exception {
        String decodedXml = StringEscapeUtils.unescapeXml(encodedXml);
        return xmlMapper.readTree(decodedXml);
    }

    // ✅ Encode XML string
    public String encodeXml(String rawXml) {
        return StringEscapeUtils.escapeXml11(rawXml);
    }

    // ✅ Convert JsonNode → XML string
    public String toXml(JsonNode node) throws Exception {
        return xmlMapper.writeValueAsString(node);
    }
}
