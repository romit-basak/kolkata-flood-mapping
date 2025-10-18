# In QGIS Python Console (Plugins → Python Console):

from qgis.utils import iface
from qgis.core import QgsSymbol, QgsRendererCategory, QgsCategorizedSymbolRenderer
from PyQt5.QtGui import QColor
import random

layer = iface.activeLayer()

# Define flood-prone wards
high_risk = [61, 66, 74, 93, 108, 109, 110]
medium_risk = [75, 85, 86, 107, 111, 112]

# Create categories
categories = []

for feature in layer.getFeatures():
    ward_no = feature['WARD']
    
    # Set color based on risk
    if int(ward_no) in high_risk:
        color = QColor(255, 0, 0, 180)  # Red with transparency
    elif int(ward_no) in medium_risk:
        color = QColor(255, 165, 0, 180)  # Orange
    else:
        color = QColor(0, 255, 0, 100)  # Light green
    
    symbol = QgsSymbol.defaultSymbol(layer.geometryType())
    symbol.setColor(color)
    
    category = QgsRendererCategory(ward_no, symbol, str(ward_no))
    categories.append(category)

# Apply the renderer
renderer = QgsCategorizedSymbolRenderer('WARD', categories)
layer.setRenderer(renderer)
layer.triggerRepaint()

layer.setLabelsEnabled(True)
label_settings = QgsPalLayerSettings()
label_settings.fieldName = 'WARD'
label_settings.enabled = True

text_format = QgsTextFormat()
text_format.setSize(8)
text_format.setColor(QColor('black'))
buffer = QgsTextBufferSettings()
buffer.setEnabled(True)
buffer.setSize(0.5)
buffer.setColor(QColor('white'))
text_format.setBuffer(buffer)
label_settings.setFormat(text_format)

layer.setLabeling(QgsVectorLayerSimpleLabeling(label_settings))
layer.triggerRepaint()
