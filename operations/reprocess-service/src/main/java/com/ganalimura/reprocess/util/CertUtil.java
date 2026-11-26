package com.ganalimura.reprocess.util;

import java.io.FileInputStream;
import java.security.KeyStore;
import java.security.cert.X509Certificate;

public class CertUtil {

    public static String extractEnv(String p12Path, String password) {
        try {
        	
        	 System.out.print("extractEnv - start :\n"+p12Path);
            KeyStore ks = KeyStore.getInstance("PKCS12");
            ks.load(new FileInputStream(p12Path), password.toCharArray());
            System.out.print("ks - start :\n"+ks);
            String alias = ks.aliases().nextElement();
            X509Certificate cert = (X509Certificate) ks.getCertificate(alias);

            String subject = cert.getSubjectX500Principal().getName().toLowerCase();
            subject = subject.replace("\\=", "=").replace("\\,", ",");
            System.out.print("subject - start :\n"+subject);
            
            System.out.println("subject cleaned: " + subject);
            // extract env
            String envFull = subject.split("env=")[1].split(",")[0];
            String env = envFull.split("oms-")[1];

            return env;

        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }
}
