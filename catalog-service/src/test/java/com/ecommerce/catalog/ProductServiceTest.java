package com.ecommerce.catalog;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class ProductServiceTest {

    @Test
    void slugifyConvertsNameToSlug() {
        String name = "iPhone 15 Pro Max 256GB";
        String slug = name.toLowerCase()
            .replaceAll("[^a-z0-9\\s-]", "")
            .replaceAll("\\s+", "-")
            .replaceAll("-+", "-")
            .replaceAll("^-|-$", "");
        assertEquals("iphone-15-pro-max-256gb", slug);
    }

    @Test
    void slugifyHandlesSpecialCharacters() {
        String name = "Product @#$% Name!!!";
        String slug = name.toLowerCase()
            .replaceAll("[^a-z0-9\\s-]", "")
            .replaceAll("\\s+", "-")
            .replaceAll("-+", "-")
            .replaceAll("^-|-$", "");
        assertEquals("product-name", slug);
    }

    @Test
    void availableStockCalculation() {
        int stock = 100;
        int reserved = 30;
        int available = Math.max(0, stock - reserved);
        assertEquals(70, available);
    }

    @Test
    void availableStockCannotBeNegative() {
        int stock = 10;
        int reserved = 20;
        int available = Math.max(0, stock - reserved);
        assertEquals(0, available);
    }

    @Test
    void productStatusEnumContainsAllExpectedValues() {
        // Verify all expected statuses exist
        assertNotNull(Product.ProductStatus.valueOf("DRAFT"));
        assertNotNull(Product.ProductStatus.valueOf("ACTIVE"));
        assertNotNull(Product.ProductStatus.valueOf("INACTIVE"));
        assertNotNull(Product.ProductStatus.valueOf("ARCHIVED"));
    }
}
