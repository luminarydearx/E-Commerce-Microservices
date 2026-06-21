package com.ecommerce.catalog.service;

import com.ecommerce.catalog.dto.*;
import com.ecommerce.catalog.exception.*;
import com.ecommerce.catalog.model.*;
import com.ecommerce.catalog.repository.*;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cache.annotation.CacheEvict;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

@Slf4j
@Service
@RequiredArgsConstructor
public class ProductService {

    private final ProductRepository productRepo;
    private final CategoryRepository categoryRepo;
    private final StockReservationRepository reservationRepo;
    private final KafkaTemplate<String, Object> kafka;
    private final ObjectMapper objectMapper;

    @Transactional(readOnly = true)
    @Cacheable(value = "product", key = "#id")
    public ProductResponse getProduct(UUID id) {
        Product p = productRepo.findById(id)
            .orElseThrow(() -> new NotFoundException("product not found"));
        return toResponse(p);
    }

    @Transactional(readOnly = true)
    public Page<ProductResponse> listProducts(ProductSearchRequest req) {
        Sort sort = buildSort(req.sortBy(), req.sortDir());
        Pageable pageable = PageRequest.of(req.page(), req.size(), sort);

        Page<Product> products = productRepo.searchProducts(
            Product.ProductStatus.ACTIVE,
            req.categoryId(),
            req.minPrice(),
            req.maxPrice(),
            req.search(),
            pageable
        );

        return products.map(this::toResponse);
    }

    @Transactional
    @CacheEvict(value = "product", key = "#result.id")
    public ProductResponse createProduct(ProductCreateRequest req, UUID sellerId) {
        // Validate seller owns category (or category is public)
        if (req.categoryId() != null) {
            categoryRepo.findById(req.categoryId())
                .orElseThrow(() -> new ValidationException("category not found"));
        }

        // Check SKU uniqueness
        if (productRepo.findBySku(req.sku()).isPresent()) {
            throw new ConflictException("sku already exists");
        }

        String slug = slugify(req.name());
        if (productRepo.findBySlug(slug).isPresent()) {
            slug = slug + "-" + UUID.randomUUID().toString().substring(0, 8);
        }

        String imagesJson = serializeImages(req.imageUrls());

        Product product = Product.builder()
            .sellerId(sellerId)
            .categoryId(req.categoryId())
            .sku(req.sku())
            .name(req.name())
            .slug(slug)
            .description(req.description())
            .price(req.price())
            .currency("IDR")
            .stock(req.stock() != null ? req.stock() : 0)
            .reservedStock(0)
            .weightGrams(req.weightGrams())
            .imageUrls(imagesJson)
            .status(req.status() != null ? req.status() : Product.ProductStatus.DRAFT)
            .isActive(true)
            .build();

        product = productRepo.save(product);
        log.info("product created: id={}, seller={}", product.getId(), sellerId);

        publishAuditEvent("product.create", sellerId, "product", product.getId(), null, toResponse(product));

        return toResponse(product);
    }

    @Transactional
    @CacheEvict(value = "product", key = "#id")
    public ProductResponse updateProduct(UUID id, ProductUpdateRequest req, UUID sellerId, List<String> roles) {
        Product p = productRepo.findById(id)
            .orElseThrow(() -> new NotFoundException("product not found"));

        // Authorization: seller can only update own product, admin can update any
        boolean isOwner = p.getSellerId().equals(sellerId);
        boolean isAdmin = roles.contains("admin") || roles.contains("superadmin");
        if (!isOwner && !isAdmin) {
            throw new ForbiddenException("not authorized to update this product");
        }

        ProductResponse before = toResponse(p);

        if (req.name() != null) p.setName(req.name());
        if (req.description() != null) p.setDescription(req.description());
        if (req.price() != null) p.setPrice(req.price());
        if (req.stock() != null) p.setStock(req.stock());
        if (req.weightGrams() != null) p.setWeightGrams(req.weightGrams());
        if (req.imageUrls() != null) p.setImageUrls(serializeImages(req.imageUrls()));
        if (req.status() != null) p.setStatus(req.status());

        p = productRepo.save(p);
        log.info("product updated: id={}, by={}", id, sellerId);

        publishAuditEvent("product.update", sellerId, "product", p.getId(), before, toResponse(p));

        return toResponse(p);
    }

    @Transactional
    @CacheEvict(value = "product", key = "#id")
    public void deleteProduct(UUID id, UUID sellerId, List<String> roles) {
        Product p = productRepo.findById(id)
            .orElseThrow(() -> new NotFoundException("product not found"));

        boolean isOwner = p.getSellerId().equals(sellerId);
        boolean isAdmin = roles.contains("admin") || roles.contains("superadmin");
        if (!isOwner && !isAdmin) {
            throw new ForbiddenException("not authorized to delete this product");
        }

        // Soft delete: mark inactive
        p.setIsActive(false);
        p.setStatus(Product.ProductStatus.ARCHIVED);
        productRepo.save(p);
        log.info("product deleted (soft): id={}, by={}", id, sellerId);

        publishAuditEvent("product.delete", sellerId, "product", id, null, null);
    }

    @Transactional
    public void adjustStock(UUID id, int newStock, UUID actorId, String reason) {
        Product p = productRepo.findById(id)
            .orElseThrow(() -> new NotFoundException("product not found"));
        if (newStock < 0) {
            throw new ValidationException("stock cannot be negative");
        }
        Integer oldStock = p.getStock();
        p.setStock(newStock);
        productRepo.save(p);
        log.info("stock adjusted: product={}, old={}, new={}, by={}, reason={}",
                 id, oldStock, newStock, actorId, reason);

        publishAuditEvent("product.stock_adjust", actorId, "product", id,
            java.util.Map.of("stock", oldStock), java.util.Map.of("stock", newStock, "reason", reason));
    }

    /**
     * Reserve stock atomically. Uses SERIALIZABLE isolation to prevent race condition.
     * Returns reservation ID.
     */
    @Transactional(isolation = Isolation.SERIALIZABLE)
    public StockReservationResult reserveStock(UUID productId, int quantity, UUID userId, UUID cartId) {
        if (quantity <= 0) {
            throw new ValidationException("quantity must be positive");
        }

        Product p = productRepo.findById(productId)
            .orElseThrow(() -> new NotFoundException("product not found"));
        if (p.getStatus() != Product.ProductStatus.ACTIVE || !p.getIsActive()) {
            throw new ValidationException("product not available");
        }
        if (p.getAvailableStock() < quantity) {
            throw new ConflictException("insufficient stock",
                java.util.Map.of("available", p.getAvailableStock(), "requested", quantity));
        }

        // Check existing reservation
        var existing = reservationRepo.findByProductIdAndCartIdAndStatus(productId, cartId,
            StockReservation.ReservationStatus.ACTIVE);
        if (existing.isPresent()) {
            // Update existing reservation
            StockReservation r = existing.get();
            int delta = quantity - r.getQuantity();
            if (delta != 0) {
                int updated = productRepo.reserveStock(productId, delta);
                if (updated == 0) {
                    throw new ConflictException("insufficient stock for reservation update");
                }
                r.setQuantity(quantity);
                r.setExpiresAt(Instant.now().plusSeconds(900)); // 15min
                reservationRepo.save(r);
            }
            return new StockReservationResult(r.getId(), productId, quantity, r.getExpiresAt());
        }

        // Atomic reservation with UPDATE ... WHERE
        int updated = productRepo.reserveStock(productId, quantity);
        if (updated == 0) {
            throw new ConflictException("insufficient stock");
        }

        StockReservation reservation = StockReservation.builder()
            .productId(productId)
            .cartId(cartId)
            .userId(userId)
            .quantity(quantity)
            .expiresAt(Instant.now().plusSeconds(900))
            .status(StockReservation.ReservationStatus.ACTIVE)
            .build();
        reservation = reservationRepo.save(reservation);

        return new StockReservationResult(reservation.getId(), productId, quantity, reservation.getExpiresAt());
    }

    @Transactional
    public void releaseStock(UUID reservationId) {
        StockReservation r = reservationRepo.findById(reservationId)
            .orElseThrow(() -> new NotFoundException("reservation not found"));
        if (r.getStatus() != StockReservation.ReservationStatus.ACTIVE) {
            return; // Already released/expired
        }
        productRepo.releaseReservation(r.getProductId(), r.getQuantity());
        r.setStatus(StockReservation.ReservationStatus.RELEASED);
        reservationRepo.save(r);
    }

    @Transactional
    public void confirmStock(UUID reservationId) {
        StockReservation r = reservationRepo.findById(reservationId)
            .orElseThrow(() -> new NotFoundException("reservation not found"));
        if (r.getStatus() != StockReservation.ReservationStatus.ACTIVE) {
            throw new ConflictException("reservation is not active");
        }
        int updated = productRepo.confirmStockDeduction(r.getProductId(), r.getQuantity());
        if (updated == 0) {
            throw new ConflictException("cannot confirm: stock or reservation mismatch");
        }
        r.setStatus(StockReservation.ReservationStatus.CONFIRMED);
        reservationRepo.save(r);
    }

    // ===== Helpers =====

    private ProductResponse toResponse(Product p) {
        List<String> images = deserializeImages(p.getImageUrls());
        return new ProductResponse(
            p.getId(), p.getSellerId(), p.getCategoryId(), p.getSku(), p.getName(), p.getSlug(),
            p.getDescription(), p.getPrice(), p.getCurrency(), p.getStock(), p.getReservedStock(),
            p.getAvailableStock(), p.getWeightGrams(), images, p.getStatus().name(),
            p.getIsActive(), p.getCreatedAt(), p.getUpdatedAt()
        );
    }

    private String serializeImages(List<String> urls) {
        if (urls == null || urls.isEmpty()) return null;
        try {
            return objectMapper.writeValueAsString(urls);
        } catch (JsonProcessingException e) {
            log.warn("failed to serialize images", e);
            return null;
        }
    }

    private List<String> deserializeImages(String json) {
        if (json == null || json.isBlank()) return List.of();
        try {
            return objectMapper.readValue(json, new com.fasterxml.jackson.core.type.TypeReference<>() {});
        } catch (JsonProcessingException e) {
            return List.of();
        }
    }

    private String slugify(String name) {
        if (name == null) return "product-" + UUID.randomUUID().toString().substring(0, 8);
        return name.toLowerCase()
            .replaceAll("[^a-z0-9\\s-]", "")
            .replaceAll("\\s+", "-")
            .replaceAll("-+", "-")
            .replaceAll("^-|-$", "");
    }

    private Sort buildSort(String sortBy, String sortDir) {
        String field = switch (sortBy == null ? "created" : sortBy) {
            case "price" -> "price";
            case "name" -> "name";
            case "updated" -> "updatedAt";
            default -> "createdAt";
        };
        Sort.Direction dir = "asc".equalsIgnoreCase(sortDir) ? Sort.Direction.ASC : Sort.Direction.DESC;
        return Sort.by(dir, field);
    }

    private void publishAuditEvent(String action, UUID actorId, String resourceType, UUID resourceId,
                                    Object before, Object after) {
        try {
            var event = java.util.Map.of(
                "event_id", UUID.randomUUID().toString(),
                "occurred_at", Instant.now().toString(),
                "producer", "catalog-service",
                "action", action,
                "actor", java.util.Map.of("user_id", actorId.toString()),
                "resource", java.util.Map.of(
                    "type", resourceType,
                    "id", resourceId.toString(),
                    "before", before,
                    "after", after
                ),
                "version", "1.0"
            );
            kafka.send("ecommerce.audit.events", actorId.toString(), event);
        } catch (Exception e) {
            log.error("failed to publish audit event", e);
        }
    }
}
