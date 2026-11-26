// Read data used during reprocessing from Sterling XML responses.
package com.ganalimura.reprocess.util;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.dataformat.xml.XmlMapper;

import java.util.*;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class ReprocessXmlParser {

    public static Map<String, String> extractAttributes(String decodedXml) {

        Map<String, String> result = new HashMap<>();

        try {
            // ✅ Step 1: Extract only <Attribute .../> using regex
            List<String> attributeList = new ArrayList<>();

            Pattern pattern = Pattern.compile("<Attribute[^>]*/>");
            Matcher matcher = pattern.matcher(decodedXml);
           

            while (matcher.find()) {
                String match = matcher.group();

                System.out.println("✅ Found Attribute: " + match); // 👈 important

                attributeList.add(match);
            }

            // ❌ If no attributes found
            if (attributeList.isEmpty()) {
                System.out.println("⚠️ No Attribute tags found");
                return result;
            }

            // ✅ Step 2: Wrap into valid XML
            StringBuilder sb = new StringBuilder();
            sb.append("<Root>");

            for (String attr : attributeList) {
                sb.append(attr);
            }

            sb.append("</Root>");

            String safeXml = sb.toString();
            System.out.println("safeXml: " + safeXml);
            // ✅ Step 3: Parse XML safely
            XmlMapper xmlMapper = new XmlMapper();
            JsonNode root = xmlMapper.readTree(safeXml);

            System.out.println("ROOT JSON: " + root);

            // ✅ Get correct Attribute node
            JsonNode attributes;

            if (root.has("Attribute")) {
                attributes = root.path("Attribute");
            } else {
                attributes = root.path("Root").path("Attribute");
            }

            // ✅ Extract values
            if (attributes.isArray()) {
                for (JsonNode attr : attributes) {
                    String name = attr.path("Name").asText();
                    String value = attr.path("Value").asText();

                    System.out.println(name + " → " + value);

                    result.put(name, value);
                }
            } else {
                String name = attributes.path("Name").asText();
                String value = attributes.path("Value").asText();

                result.put(name, value);
            }

        } catch (Exception e) {
            e.printStackTrace();
        }

        return result;
    }

    public static String extractOrderNo(String xml) {
        Pattern pattern = Pattern.compile("<Order[^>]*OrderNo=\"([^\"]+)\"");
        Matcher matcher = pattern.matcher(xml);
        if (matcher.find()) {
            return matcher.group(1);
        }
        return null;
    }
}