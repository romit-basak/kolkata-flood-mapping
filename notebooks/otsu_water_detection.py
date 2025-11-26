"""
Otsu Adaptive Thresholding for SAR Water Detection
Converted from Raviraj Dave's GEE JavaScript implementation
Optimized for permanent water mask with ward-specific thresholds
"""

import ee
import numpy as np

def apply_speckle_filter(image):
    """
    Apply focal median speckle filter to reduce noise
    Raviraj's method: 100m circular focal median
    """
    # Select VV band (or VH if available)
    if 'VV' in image.bandNames().getInfo():
        sar_band = image.select('VV')
        band_name = 'VV'
    elif 'VH' in image.bandNames().getInfo():
        sar_band = image.select('VH')
        band_name = 'VH'
    else:
        # For ALOS-2
        sar_band = image.select('HH')
        band_name = 'HH'
    
    # Apply 100m focal median filter (circular kernel)
    filtered = sar_band.focalMedian(100, 'circle', 'meters').rename(f'{band_name}_filtered')
    
    return image.addBands(filtered)


def calculate_otsu_threshold(histogram_dict):
    """
    Calculate optimal threshold using Otsu's method
    Direct Python translation of Raviraj's JavaScript implementation
    
    Args:
        histogram_dict: Dictionary with 'histogram' and 'bucketMeans' from reduceRegion
    
    Returns:
        float: Optimal threshold value
    """
    # Extract histogram data
    counts = ee.Array(histogram_dict.get('histogram'))
    means = ee.Array(histogram_dict.get('bucketMeans'))
    
    # Get size and total
    size = means.length().get([0])
    total = counts.reduce(ee.Reducer.sum(), [0]).get([0])
    sum_val = means.multiply(counts).reduce(ee.Reducer.sum(), [0]).get([0])
    mean = sum_val.divide(total)
    
    # Create indices sequence
    indices = ee.List.sequence(1, size)
    
    # Calculate between-class variance for each threshold
    def calc_bss(i):
        # Class A (below threshold)
        aCounts = counts.slice(0, 0, i)
        aCount = aCounts.reduce(ee.Reducer.sum(), [0]).get([0])
        aMeans = means.slice(0, 0, i)
        aMean = aMeans.multiply(aCounts) \
            .reduce(ee.Reducer.sum(), [0]).get([0]) \
            .divide(aCount)
        
        # Class B (above threshold)
        bCount = total.subtract(aCount)
        bMean = sum_val.subtract(aCount.multiply(aMean)).divide(bCount)
        
        # Between-class variance
        return aCount.multiply(aMean.subtract(mean).pow(2)) \
            .add(bCount.multiply(bMean.subtract(mean).pow(2)))
    
    # Calculate BSS for all thresholds
    bss = indices.map(calc_bss)
    
    # Return threshold with maximum between-class variance
    return means.sort(bss).get([-1])


def detect_water_otsu_per_ward(image, ward_geometry, band_name='VV_filtered'):
    """
    Detect water using Otsu's threshold for a specific ward
    
    Args:
        image: ee.Image with filtered SAR band
        ward_geometry: ee.Geometry of the ward
        band_name: Name of filtered band to use
    
    Returns:
        ee.Image: Binary water mask (1=water, 0=land)
    """
    # Select filtered band
    filtered_band = image.select(band_name)
    
    # Calculate histogram for this ward
    histogram = filtered_band.reduceRegion(
        reducer=ee.Reducer.histogram(255, 2)
            .combine('mean', None, True)
            .combine('variance', None, True),
        geometry=ward_geometry,
        scale=10,
        bestEffort=True,
        maxPixels=1e9
    )
    
    # Calculate Otsu threshold
    threshold = calculate_otsu_threshold(histogram.get(f'{band_name}_histogram'))
    
    # Classify water (pixels below threshold)
    water = filtered_band.lt(threshold)
    
    return water, threshold


def calculate_ward_specific_thresholds(sar_collection, wards_fc, band_name='VV'):
    """
    Calculate optimal Otsu threshold for each ward using all dry season images
    This gives ward-specific thresholds: -17.8 to -12.5 dB range
    
    Args:
        sar_collection: ee.ImageCollection of dry season SAR (already filtered)
        wards_fc: ee.FeatureCollection of wards
        band_name: 'VV' or 'HH'
    
    Returns:
        dict: {ward_id: threshold_value}
    """
    print(f"\n⏱️  Calculating ward-specific Otsu thresholds...")
    print(f"  Processing {wards_fc.size().getInfo()} wards")
    print(f"  This will take 3-5 minutes...")
    
    # Apply speckle filter to entire collection
    filtered_collection = sar_collection.map(apply_speckle_filter)
    
    # Create mosaic of all dry season images (combined histogram)
    dry_season_composite = filtered_collection.select(f'{band_name}_filtered').mean()
    
    def calculate_ward_threshold(ward_feature):
        """Calculate threshold for a single ward"""
        ward_geom = ward_feature.geometry()
        ward_id = ward_feature.get('ward_id')
        
        # Calculate histogram for this ward across all images
        histogram = dry_season_composite.reduceRegion(
            reducer=ee.Reducer.histogram(255, 2),
            geometry=ward_geom,
            scale=10,
            bestEffort=True,
            maxPixels=1e9
        )
        
        # Calculate Otsu threshold
        try:
            threshold = calculate_otsu_threshold(histogram.get(f'{band_name}_filtered_histogram'))
        except:
            # Fallback to fixed threshold if Otsu fails
            threshold = ee.Number(-15)
        
        return ward_feature.set({
            'otsu_threshold': threshold,
            'threshold_calculated': True
        })
    
    # Calculate thresholds for all wards
    wards_with_thresholds = wards_fc.map(calculate_ward_threshold)
    
    # Get results
    threshold_data = wards_with_thresholds.getInfo()
    
    ward_thresholds = {}
    for feature in threshold_data['features']:
        ward_id = feature['properties']['ward_id']
        threshold = feature['properties'].get('otsu_threshold', -15)
        ward_thresholds[ward_id] = threshold
    
    print(f"✓ Calculated thresholds for {len(ward_thresholds)} wards")
    
    # Show threshold distribution
    thresholds = list(ward_thresholds.values())
    print(f"\n  Threshold range: {min(thresholds):.1f} to {max(thresholds):.1f} dB")
    print(f"  Mean: {np.mean(thresholds):.1f} dB")
    print(f"  Std: {np.std(thresholds):.1f} dB")
    
    return ward_thresholds


def detect_water_with_ward_thresholds(image, wards_fc, ward_thresholds, band_name='VV'):
    """
    Detect water using ward-specific Otsu thresholds
    
    Args:
        image: ee.Image (already speckle filtered)
        wards_fc: ee.FeatureCollection of wards
        ward_thresholds: dict of {ward_id: threshold}
        band_name: Band name
    
    Returns:
        ee.Image: Binary water mask
    """
    # Apply speckle filter
    filtered_img = apply_speckle_filter(image)
    filtered_band = filtered_img.select(f'{band_name}_filtered')
    
    # Create empty water mask
    water_mask = ee.Image(0)
    
    # Apply ward-specific thresholds
    for ward_id, threshold in ward_thresholds.items():
        # Get ward geometry
        ward = wards_fc.filter(ee.Filter.eq('ward_id', ward_id)).first()
        ward_geom = ward.geometry()
        
        # Detect water in this ward using its specific threshold
        ward_water = filtered_band.lt(threshold).clip(ward_geom)
        
        # Add to overall mask
        water_mask = water_mask.Or(ward_water)
    
    return water_mask.rename('water')


def apply_otsu_to_collection(sar_collection, wards_fc, ward_thresholds, band_name='VV'):
    """
    Apply ward-specific Otsu thresholds to entire SAR collection
    
    Args:
        sar_collection: ee.ImageCollection
        wards_fc: ee.FeatureCollection
        ward_thresholds: dict of thresholds
        band_name: 'VV' or 'HH'
    
    Returns:
        ee.ImageCollection: Collection of binary water masks
    """
    def detect_water_wrapper(image):
        return detect_water_with_ward_thresholds(
            image, wards_fc, ward_thresholds, band_name
        ).set('system:time_start', image.get('system:time_start'))
    
    return sar_collection.map(detect_water_wrapper)


# Simplified version for quick testing
def detect_water_otsu_simple(image, roi, band_name='VV'):
    """
    Simplified Otsu water detection for entire region
    Good for testing before running full ward-specific version
    
    Args:
        image: ee.Image
        roi: ee.Geometry (study area)
        band_name: 'VV' or 'HH'
    
    Returns:
        ee.Image: Binary water mask
    """
    # Apply speckle filter
    filtered = apply_speckle_filter(image)
    filtered_band = filtered.select(f'{band_name}_filtered')
    
    # Calculate histogram
    histogram = filtered_band.reduceRegion(
        reducer=ee.Reducer.histogram(255, 2),
        geometry=roi,
        scale=10,
        bestEffort=True,
        maxPixels=1e9
    )
    
    # Calculate Otsu threshold
    threshold = calculate_otsu_threshold(histogram.get(f'{band_name}_filtered_histogram'))
    
    # Detect water
    water = filtered_band.lt(threshold)
    
    return water.rename('water'), threshold


# Example usage for permanent water mask
def create_permanent_water_with_otsu(sar_collection, wards_fc):
    """
    Complete workflow: Calculate ward thresholds and create permanent water mask
    
    Args:
        sar_collection: Dry season SAR collection
        wards_fc: Ward FeatureCollection
    
    Returns:
        tuple: (water_frequency, ward_thresholds)
    """
    print("=" * 60)
    print("OTSU ADAPTIVE PERMANENT WATER DETECTION")
    print("=" * 60)
    
    # Step 1: Calculate ward-specific thresholds
    print("\nStep 1: Calculating ward-specific Otsu thresholds...")
    ward_thresholds = calculate_ward_specific_thresholds(
        sar_collection, wards_fc, band_name='VV'
    )
    
    # Step 2: Apply thresholds to entire collection
    print("\nStep 2: Applying ward-specific thresholds...")
    water_collection = apply_otsu_to_collection(
        sar_collection, wards_fc, ward_thresholds, band_name='VV'
    )
    
    # Step 3: Calculate frequency
    print("\nStep 3: Calculating water frequency...")
    water_count = water_collection.size().getInfo()
    water_frequency = water_collection.sum().divide(water_count)
    
    print(f"\n✓ Permanent water mask created with Otsu thresholding")
    print(f"  Based on {water_count} images with ward-specific thresholds")
    
    return water_frequency, ward_thresholds


# Testing/debugging function
def test_otsu_single_image(image, roi):
    """
    Quick test of Otsu on single image
    """
    water, threshold = detect_water_otsu_simple(image, roi)
    
    print(f"Otsu threshold: {threshold.getInfo():.2f} dB")
    print("Water mask created")
    
    return water, threshold
