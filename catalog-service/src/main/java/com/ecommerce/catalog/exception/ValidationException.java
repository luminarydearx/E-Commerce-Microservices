package com.ecommerce.catalog.exception;

import java.util.Map;

public class ValidationException extends RuntimeException {
    private final Map<String, Object> details;
    public ValidationException(String message) { this(message, null); }
    public ValidationException(String message, Map<String, Object> details) {
        super(message);
        this.details = details;
    }
    public Map<String, Object> getDetails() { return details; }
}
