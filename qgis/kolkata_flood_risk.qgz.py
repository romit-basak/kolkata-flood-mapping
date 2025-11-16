from qgis.core import *
from qgis.utils import *

# Get your ward layer
ward_layer = QgsProject.instance().mapLayersByName("KMA Wards (281)")[0]

# Create a SIMPLE renderer (replacing the categorized one)
symbol = QgsFillSymbol.createSimple({
    'color': '255,255,255,0',  # Transparent fill
    'outline_color': '#FF0000',  # Red boundaries
    'outline_width': '1.0',
    'outline_style': 'solid'
})

# Create new simple renderer
simple_renderer = QgsSingleSymbolRenderer(symbol)

# Replace the existing renderer
ward_layer.setRenderer(simple_renderer)
ward_layer.triggerRepaint()

print("✓ Ward boundaries now visible in red")