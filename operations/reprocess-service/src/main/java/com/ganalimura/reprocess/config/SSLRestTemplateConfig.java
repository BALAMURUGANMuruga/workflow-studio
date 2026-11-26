package com.ganalimura.reprocess.config;

import org.apache.hc.client5.http.impl.classic.CloseableHttpClient;
import org.apache.hc.client5.http.impl.classic.HttpClients;

import org.springframework.http.client.HttpComponentsClientHttpRequestFactory;
import org.springframework.web.client.RestTemplate;

public class SSLRestTemplateConfig {

    public static RestTemplate getRestTemplate() {
        try {
            CloseableHttpClient httpClient = HttpClients.custom().build();

            return new RestTemplate(
                    new HttpComponentsClientHttpRequestFactory(httpClient)
            );

        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }
}