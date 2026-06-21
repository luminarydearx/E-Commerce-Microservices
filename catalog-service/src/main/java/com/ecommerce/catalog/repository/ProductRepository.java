package com.ecommerce.catalog.repository;

import com.ecommerce.catalog.model.Product;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.Optional;
import java.util.UUID;

@Repository
public interface ProductRepository extends JpaRepository<Product, UUID> {

    Optional<Product> findBySku(String sku);
    Optional<Product> findBySlug(String slug);

    Page<Product> findBySellerIdAndIsActiveTrue(UUID sellerId, Pageable pageable);

    Page<Product> findByCategoryIdAndIsActiveTrueAndStatus(UUID categoryId, Product.ProductStatus status, Pageable pageable);

    Page<Product> findByIsActiveTrueAndStatus(Product.ProductStatus status, Pageable pageable);

    @Query("SELECT p FROM Product p WHERE p.isActive = true AND p.status = :status " +
           "AND (:categoryId IS NULL OR p.categoryId = :categoryId) " +
           "AND (:minPrice IS NULL OR p.price >= :minPrice) " +
           "AND (:maxPrice IS NULL OR p.price <= :maxPrice) " +
           "AND (:search IS NULL OR LOWER(p.name) LIKE LOWER(CONCAT('%', :search, '%')))")
    Page<Product> searchProducts(
            @Param("status") Product.ProductStatus status,
            @Param("categoryId") UUID categoryId,
            @Param("minPrice") java.math.BigDecimal minPrice,
            @Param("maxPrice") java.math.BigDecimal maxPrice,
            @Param("search") String search,
            Pageable pageable
    );

    /**
     * Atomically reserve stock with pessimistic lock. Returns 1 if successful.
     * Equivalent to: SELECT ... FOR UPDATE; UPDATE ...
     */
    @Modifying
    @Query(value = "UPDATE catalog.products SET reserved_stock = reserved_stock + :qty " +
                   "WHERE id = :productId AND stock - reserved_stock >= :qty",
           nativeQuery = true)
    int reserveStock(@Param("productId") UUID productId, @Param("qty") int qty);

    @Modifying
    @Query(value = "UPDATE catalog.products SET reserved_stock = reserved_stock - :qty " +
                   "WHERE id = :productId AND reserved_stock >= :qty",
           nativeQuery = true)
    int releaseReservation(@Param("productId") UUID productId, @Param("qty") int qty);

    @Modifying
    @Query(value = "UPDATE catalog.products SET stock = stock - :qty, reserved_stock = reserved_stock - :qty " +
                   "WHERE id = :productId AND stock >= :qty AND reserved_stock >= :qty",
           nativeQuery = true)
    int confirmStockDeduction(@Param("productId") UUID productId, @Param("qty") int qty);
}
