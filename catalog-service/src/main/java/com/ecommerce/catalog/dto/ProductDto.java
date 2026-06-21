package com.ecommerce.catalog.dto;

import jakarta.validation.constraints.*;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

public record ProductResponse(
    UUID id,
    UUID sellerId,
    UUID categoryId,
    String sku,
    String name,
    String slug,
    String description,
    BigDecimal price,
    String currency,
    Integer stock,
    Integer reservedStock,
    Integer availableStock,
    Integer weightGrams,
    List<String> imageUrls,
    String status,
    Boolean isActive,
    Instant createdAt,
    Instant updatedAt
) {}

public record ProductCreateRequest(
    @NotBlank @Size(max = 100) String sku,
    @NotBlank @Size(max = 255) String name,
    @Size(max = 5000) String description,
    @NotNull @DecimalMin(value = "0.01") @Digits(integer = 17, fraction = 2) BigDecimal price,
    @Min(0) Integer stock,
    @Positive Integer weightGrams,
    List<String> imageUrls,
    UUID categoryId,
    String status
) {}

public record ProductUpdateRequest(
    @Size(max = 255) String name,
    @Size(max = 5000) String description,
    @DecimalMin(value = "0.01") BigDecimal price,
    @Min(0) Integer stock,
    Integer weightGrams,
    List<String> imageUrls,
    String status
) {}

public record ProductSearchRequest(
    String search,
    UUID categoryId,
    BigDecimal minPrice,
    BigDecimal maxPrice,
    String sortBy,
    String sortDir,
    @Min(0) Integer page,
    @Min(1) @Max(100) Integer size
) {
    public ProductSearchRequest {
        if (page == null) page = 0;
        if (size == null) size = 20;
    }
}

public record StockAdjustRequest(
    @NotNull @Min(0) Integer newStock,
    @Size(max = 500) String reason
) {}

public record StockReservationResult(
    UUID reservationId,
    UUID productId,
    Integer quantity,
    Instant expiresAt
) {}

public record StockReserveRequest(
    @NotNull UUID productId,
    @NotNull @Min(1) Integer quantity,
    @NotNull UUID userId,
    @NotNull UUID cartId
) {}
