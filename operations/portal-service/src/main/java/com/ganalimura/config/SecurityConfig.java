package com.ganalimura.config;

import java.io.IOException;
import java.util.List;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.CorsConfigurationSource;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;
import org.springframework.web.filter.OncePerRequestFilter;

import com.ganalimura.security.JwtService;

@Configuration
public class SecurityConfig {

    @Bean
    PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder(12);
    }

    @Bean
    SecurityFilterChain securityFilterChain(
            HttpSecurity http,
            JwtService jwtService) throws Exception {

        http
            .csrf(csrf -> csrf.disable())
            .cors(cors -> {})
            .sessionManagement(session ->
                session.sessionCreationPolicy(
                    SessionCreationPolicy.STATELESS))
            .authorizeHttpRequests(auth -> auth
            	    .requestMatchers(
            	        org.springframework.http.HttpMethod.POST,
            	        "/api/auth/login",
            	        "/api/auth/register",
            	        "/api/auth/forgot-password",
            	        "/api/auth/reset-password"
            	    ).permitAll()
            	    .anyRequest().authenticated()
            	)
            .addFilterBefore(
                new JwtAuthenticationFilter(jwtService),
                UsernamePasswordAuthenticationFilter.class
            );

        return http.build();
    }

    @Bean
    CorsConfigurationSource corsConfigurationSource() {
        CorsConfiguration config = new CorsConfiguration();
        config.setAllowedOrigins(List.of("http://localhost:4200", "http://127.0.0.1:4200"));
        config.setAllowedMethods(
            List.of("GET", "POST", "PUT", "DELETE", "OPTIONS"));
        config.setAllowedHeaders(
            List.of("Authorization", "Content-Type"));
        config.setAllowCredentials(false);

        UrlBasedCorsConfigurationSource source =
            new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", config);
        return source;
    }

    static class JwtAuthenticationFilter
            extends OncePerRequestFilter {

        private final JwtService jwtService;

        JwtAuthenticationFilter(JwtService jwtService) {
            this.jwtService = jwtService;
        }
        
        @Override
        protected boolean shouldNotFilter(HttpServletRequest request) {
            String path = request.getServletPath();

            return "POST".equalsIgnoreCase(request.getMethod())
                    && (
                        path.equals("/api/auth/login")
                        || path.equals("/api/auth/register")
                        || path.equals("/api/auth/forgot-password")
                        || path.equals("/api/auth/reset-password")
                    );
        }

        @Override
        protected void doFilterInternal(
                HttpServletRequest request,
                HttpServletResponse response,
                FilterChain chain)
                throws ServletException, IOException {

            String header = request.getHeader("Authorization");
            if (header == null && "/ws".equals(request.getServletPath())) {
                String protocols = request.getHeader("Sec-WebSocket-Protocol");
                if (protocols != null) {
                    String[] offered = protocols.split(",", -1);
                    if (offered.length == 2 && "workflow-portal".equals(offered[0].trim())) {
                        header = "Bearer " + offered[1].trim();
                    }
                }
            }

            if (header != null && header.startsWith("Bearer ")) {
                try {
                    var claims = jwtService.validateAndGetClaims(
                        header.substring(7));

                    String username = claims.getSubject();

                    if (username != null
                            && SecurityContextHolder.getContext()
                                .getAuthentication() == null) {

                        var authentication =
                            new UsernamePasswordAuthenticationToken(
                                username, null, List.of());

                        SecurityContextHolder.getContext()
                            .setAuthentication(authentication);
                    }
                } catch (io.jsonwebtoken.JwtException
                        | IllegalArgumentException ex) {
                    response.sendError(
                        HttpServletResponse.SC_UNAUTHORIZED,
                        "Invalid or expired token");
                    return;
                }
            }

            chain.doFilter(request, response);
        }
    }
}
