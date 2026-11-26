package com.ganalimura.service;

import org.springframework.stereotype.Service;
import org.w3c.dom.Document;
import org.w3c.dom.Node;
import org.w3c.dom.NodeList;
import org.xml.sax.InputSource;

import javax.xml.parsers.DocumentBuilderFactory;
import javax.xml.xpath.*;
import java.io.StringReader;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Service
public class XmlPathExtractor {

	public Map<String, String> extractSingleValues(String xml, Map<String, String> paths) {

		Map<String, String> result = new HashMap<>();

		try {
			Document doc = DocumentBuilderFactory.newInstance().newDocumentBuilder()
					.parse(new InputSource(new StringReader(xml)));

			XPath xpath = XPathFactory.newInstance().newXPath();

			for (Map.Entry<String, String> entry : paths.entrySet()) {

				String value = xpath.evaluate(entry.getValue(), doc);

				result.put(entry.getKey(), value);
			}

		} catch (Exception e) {
			throw new RuntimeException(e);
		}

		return result;
	}

	public List<Map<String, String>> extractMultipleValues(String inputXml, Map<String, String> paths) {

		List<Map<String, String>> result = new ArrayList<>();

		try {
			Document doc = DocumentBuilderFactory.newInstance().newDocumentBuilder()
					.parse(new InputSource(new StringReader(inputXml)));

			XPath xpath = XPathFactory.newInstance().newXPath();

			// Check if we need to extract from multiple OrderLine nodes
			boolean hasOrderLines = paths.values().stream().anyMatch(path -> path.contains("/Order/OrderLines/OrderLine"));

			if (hasOrderLines) {
				// Get all OrderLine nodes
				NodeList nodes = (NodeList) xpath.evaluate("/Order/OrderLines/OrderLine", doc, XPathConstants.NODESET);

				for (int i = 0; i < nodes.getLength(); i++) {

					Node node = nodes.item(i);
					Map<String, String> values = new HashMap<>();

					for (Map.Entry<String, String> entry : paths.entrySet()) {

						String key = entry.getKey();
						String path = entry.getValue();

						// Replace base path to current node
						String relativePath = path.replace("/Order/OrderLines/OrderLine", ".");

						String value = xpath.evaluate(relativePath, node);
						values.put(key, value);
					}

					result.add(values);
				}
			} else {
				// Extract single values from document root
				Map<String, String> values = new HashMap<>();
				for (Map.Entry<String, String> entry : paths.entrySet()) {
					String key = entry.getKey();
					String path = entry.getValue();
					String value = xpath.evaluate(path, doc);
					values.put(key, value);
				}
				result.add(values);
			}

		} catch (Exception e) {
			e.printStackTrace();
		}

		return result;
	}

	public String extractValue(String xml, String xpathExpression) {
		try {
			Document doc = DocumentBuilderFactory.newInstance().newDocumentBuilder()
					.parse(new InputSource(new StringReader(xml)));

			XPath xpath = XPathFactory.newInstance().newXPath();
			return xpath.evaluate(xpathExpression, doc);

		} catch (Exception e) {
			throw new RuntimeException("Failed to extract value from XML", e);
		}
	}
}
