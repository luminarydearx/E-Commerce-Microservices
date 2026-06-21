package com.ecommerce.catalog.repository;

import com.ecommerce.catalog.model.StockReservation;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.Optional;
import java.util.UUID;

@Repository
public interface StockReservationRepository extends JpaRepository<StockReservation, UUID> {
    Optional<StockReservation> findByProductIdAndCartIdAndStatus(UUID productId, UUID cartId, StockReservation.ReservationStatus status);
}
