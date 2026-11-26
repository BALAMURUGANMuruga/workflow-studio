package com.ganalimura.util;

import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Component;

@Component
public class XmlUtil {
	
	public String loadXml(String fileName) {
		try {
			ClassPathResource resource=new ClassPathResource(fileName);
			return new String(resource.getInputStream().readAllBytes());
		} catch(Exception e) {
			throw new RuntimeException("Failed to load xml :"+e.getMessage());
			
		}
	}

}
