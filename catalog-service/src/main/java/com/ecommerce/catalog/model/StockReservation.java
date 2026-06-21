package com.ecommerce.catalog.model;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;
import org.hibernate.annotations.UuidGenerator;

import java.time.Instant;
import java.util.UUID;

/**
 * Inventory reservation for checkout flow. Created when user starts checkout,
 * released when order is confirmed or after timeout.
 */
@Entity
@Table(name = "stock_reservations", schema = "catalog",
       uniqueConstraints = @UniqueConstraint(columnNames = {"product_id", "cart_id"}))
@Getter @Setter
@NoArgsConstructor @AllArgsConstructor
@Builder
public class StockReservation {

    @Id
    @GeneratedValue(generator = "uuid2")
    @UuidGenerator
    private UUID id;

    @Column(name = "product_id", nullable = false)
    private UUID productId;

    @Column(name = "cart_id", nullable = false)
    private UUID cartId;

    @Column(name = "user_id", nullable = false)
    private UUID userId;

    @Column(name = "quantity", nullable = false)
    private Integer quantity;

    @Column(name = "expires_at", nullable = false)
    private Instant expiresAt;

    @Column(name = "status", nullable = false, length = 20)
    @Enumerated(EnumType.STRING)
    @Builder.Default
    private ReservationStatus status = ReservationStatus.ACTIVE;

    @CreationTimestamp
    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    @UpdateTimestamp
    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    public enum ReservationStatus {
        ACTIVE, CONFIRMED, RELEASED, EXPIRED
    }
}
