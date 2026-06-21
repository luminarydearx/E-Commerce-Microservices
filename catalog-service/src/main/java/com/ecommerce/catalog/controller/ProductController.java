package com.ecommerce.catalog.controller;

import com.ecommerce.catalog.dto.*;
import com.ecommerce.catalog.service.ProductService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.domain.Page;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.UUID;

@Slf4j
@RestController
@RequestMapping("/api/v1")
@RequiredArgsConstructor
public class ProductController {

    private final ProductService productService;

    @GetMapping("/products")
    public ResponseEntity<Page<ProductResponse>> listProducts(
        @RequestParam(required = false) String search,
        @RequestParam(required = false) UUID categoryId,
        @RequestParam(required = false) java.math.BigDecimal minPrice,
        @RequestParam(required = false) java.math.BigDecimal maxPrice,
        @RequestParam(required = false, defaultValue = "created") String sortBy,
        @RequestParam(required = false, defaultValue = "desc") String sortDir,
        @RequestParam(required = false, defaultValue = "0") Integer page,
        @RequestParam(required = false, defaultValue = "20") Integer size
    ) {
        var req = new ProductSearchRequest(search, categoryId, minPrice, maxPrice, sortBy, sortDir, page, size);
        return ResponseEntity.ok(productService.listProducts(req));
    }

    @GetMapping("/products/{id}")
    public ResponseEntity<ProductResponse> getProduct(@PathVariable UUID id) {
        return ResponseEntity.ok(productService.getProduct(id));
    }

    @PostMapping("/products")
    @PreAuthorize("hasAnyRole('SELLER', 'ADMIN', 'SUPERADMIN')")
    public ResponseEntity<ProductResponse> createProduct(
        @Valid @RequestBody ProductCreateRequest req,
        HttpServletRequest request
    ) {
        UUID sellerId = extractUserId(request);
        return ResponseEntity.status(HttpStatus.CREATED)
            .body(productService.createProduct(req, sellerId));
    }

    @PutMapping("/products/{id}")
    @PreAuthorize("hasAnyRole('SELLER', 'ADMIN', 'SUPERADMIN')")
    public ResponseEntity<ProductResponse> updateProduct(
        @PathVariable UUID id,
        @Valid @RequestBody ProductUpdateRequest req,
        HttpServletRequest request
    ) {
        UUID sellerId = extractUserId(request);
        List<String> roles = extractRoles(request);
        return ResponseEntity.ok(productService.updateProduct(id, req, sellerId, roles));
    }

    @DeleteMapping("/products/{id}")
    @PreAuthorize("hasAnyRole('SELLER', 'ADMIN', 'SUPERADMIN')")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void deleteProduct(@PathVariable UUID id, HttpServletRequest request) {
        UUID sellerId = extractUserId(request);
        List<String> roles = extractRoles(request);
        productService.deleteProduct(id, sellerId, roles);
    }

    @PatchMapping("/products/{id}/stock")
    @PreAuthorize("hasAnyRole('SELLER', 'ADMIN', 'SUPERADMIN')")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void adjustStock(
        @PathVariable UUID id,
        @Valid @RequestBody StockAdjustRequest req,
        HttpServletRequest request
    ) {
        UUID actorId = extractUserId(request);
        productService.adjustStock(id, req.newStock(), actorId, req.reason());
    }

    // Internal API for order-service (not exposed via gateway, only mTLS)
    @PostMapping("/internal/products/{id}/reserve")
    public ResponseEntity<StockReservationResult> reserveStock(
        @PathVariable UUID id,
        @Valid @RequestBody StockReserveRequest req
    ) {
        if (!id.equals(req.productId())) {
            return ResponseEntity.badRequest().build();
        }
        return ResponseEntity.ok(productService.reserveStock(req.productId(), req.quantity(), req.userId(), req.cartId()));
    }

    @PostMapping("/internal/reservations/{reservationId}/release")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void releaseStock(@PathVariable UUID reservationId) {
        productService.releaseStock(reservationId);
    }

    @PostMapping("/internal/reservations/{reservationId}/confirm")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void confirmStock(@PathVariable UUID reservationId) {
        productService.confirmStock(reservationId);
    }

    private UUID extractUserId(HttpServletRequest request) {
        String uid = request.getHeader("X-User-Id");
        if (uid == null || uid.isBlank()) {
            throw new IllegalStateException("missing X-User-Id header");
        }
        return UUID.fromString(uid);
    }

    private List<String> extractRoles(HttpServletRequest request) {
        String roles = request.getHeader("X-User-Roles");
        if (roles == null || roles.isBlank()) return List.of();
        return List.of(roles.split(","));
    }
}
