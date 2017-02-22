#!/bin/python

# Copyright 2017, Sourcepole AG.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

import os
try:
    from urllib.request import urlopen
except:
    from urllib2 import urlopen
try:
    from urllib.parse import quote
except:
    from urllib import quote
from xml.dom.minidom import parseString
import json
import traceback


# load thumbnail from file or GetMap
def getThumbnail(configItem, resultItem, layers, crs, extent):
    if "thumbnail" in configItem:
        if os.path.exists("./assets/img/mapthumbs/" + configItem["thumbnail"]):
            resultItem["thumbnail"] = "img/mapthumbs/" + configItem["thumbnail"]
            return

    print("Using WMS GetMap to generate thumbnail for " + configItem["url"])

    # WMS GetMap request
    url = configItem["url"] + "?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&FORMAT=image/png&STYLES=&WIDTH=200&HEIGHT=100&CRS=" + crs
    bboxw = extent[2] - extent[0]
    bboxh = extent[3] - extent[1]
    bboxcx = 0.5 * (extent[0] + extent[2])
    bboxcy = 0.5 * (extent[1] + extent[3])
    imgratio = 200. / 100.
    if bboxw > bboxh:
        bboxratio = bboxw / bboxh
        if bboxratio > imgratio:
            bboxh = bboxw / imgratio
        else:
            bboxw = bboxh * imgratio
    else:
        bboxw = bboxh * imgratio
    adjustedExtent = [bboxcx - 0.5 * bboxw, bboxcy - 0.5 * bboxh,
                      bboxcx + 0.5 * bboxw, bboxcy + 0.5 * bboxh]
    url += "&BBOX=" + (",".join(map(str, adjustedExtent)))
    url += "&LAYERS=" + quote(",".join(layers).encode('utf-8'))

    try:
        request = urlopen(url)
        reply = request.read()
        basename = configItem["url"].rsplit("/")[-1] + ".png"
        with open("./assets/img/mapthumbs/" + basename, "wb") as fh:
            fh.write(reply)
        resultItem["thumbnail"] = "img/mapthumbs/" + basename
    except Exception as e:
        print("ERROR for WMS " + configItem["url"] + ":\n" + str(e))
        resultItem["error"] = "Could not get thumbnail"
        traceback.print_exc()


def getDirectChildElements(parent, tagname):
    return [node for node in parent.childNodes if node.nodeName == tagname]


def getChildElement(parent, path):
    for part in path.split("/"):
        for node in parent.childNodes:
            if node.nodeName == part:
                parent = node
                break
        else:
            return None
    return parent


def getElementValue(element):
    return element.firstChild.nodeValue if element and element.firstChild else ""


def getChildElementValue(parent, path):
    return getElementValue(getChildElement(parent, path))


# recursively get layer tree
def getLayerTree(layer, resultLayers, visibleLayers, printLayers):
    name = getChildElementValue(layer, "Name")
    title = getChildElementValue(layer, "Title")
    layers = getDirectChildElements(layer, "Layer")

    if name in printLayers:
        # skip print layers
        return

    layerEntry = {"name": name, "title": title}

    if not layers:
        if layer.getAttribute("geometryType") == "WKBNoGeometry":
            # skip layers without geometry
            return

        # layer
        layerEntry["visibility"] = layer.getAttribute("visible") == "1"
        if layerEntry["visibility"]:
            # collect visible layers
            visibleLayers.append(name)

        layerEntry["queryable"] = layer.getAttribute("queryable") == "1"
        if layerEntry["queryable"] and layer.getAttribute("displayField"):
            layerEntry["displayField"] = layer.getAttribute("displayField")

        try:
            layerEntry["attribution"] = getChildElementValue(layer, "Attribution/Title")
            onlineResource = getChildElement(layer, "Attribution/OnlineResource")
            layerEntry["attributionUrl"] = onlineResource.getAttribute("xlink:href")
        except:
            pass
        try:
            layerEntry["abstract"] = getChildElementValue(layer, "Abstract")
        except:
            pass
        try:
            onlineResource = getChildElement(layer, "DataURL/OnlineResource")
            layerEntry["dataUrl"] = onlineResource.getAttribute("xlink:href")
        except:
            pass
        try:
            onlineResource = getChildElement(layer, "MetadataURL/OnlineResource")
            layerEntry["metadataUrl"] = onlineResource.getAttribute("xlink:href")
        except:
            pass
        try:
            keywords = []
            for keyword in getChildElement(layer, "KeywordList").getElementsByTagName("Keyword"):
                keywords.append(getElementValue(keyword))
            layerEntry["keywords"] = ",".join(keywords)
        except:
            pass

        if layer.getAttribute("transparency"):
            layerEntry["opacity"] = 255 - int(float(layer.getAttribute("transparency")) / 100 * 255)
        else:
            layerEntry["opacity"] = 255
        minScale = getChildElementValue(layer, "MinScaleDenominator")
        maxScale = getChildElementValue(layer, "MaxScaleDenominator")
        if minScale and maxScale:
            layerEntry["minScale"] = int(float(minScale))
            layerEntry["maxScale"] = int(float(maxScale))

        # use geographic bounding box, as default CRS may have inverted axis order with WMS 1.3.0
        layerEntry["crs"] = "EPSG:4326"
        geoBBox = getChildElement(layer, "EX_GeographicBoundingBox")
        layerEntry["extent"] = [
            float(getChildElementValue(geoBBox, "westBoundLongitude")),
            float(getChildElementValue(geoBBox, "southBoundLatitude")),
            float(getChildElementValue(geoBBox, "eastBoundLongitude")),
            float(getChildElementValue(geoBBox, "northBoundLatitude"))
        ]
    else:
        # group
        layerEntry["sublayers"] = []
        layerEntry["expanded"] = True
        for sublayer in layers:
            getLayerTree(sublayer, layerEntry["sublayers"], visibleLayers, printLayers)

        if not layerEntry["sublayers"]:
            # skip empty groups
            return

    resultLayers.append(layerEntry)


# parse GetCapabilities for theme
def getTheme(configItem, resultItem):
    resultItem["url"] = configItem["url"]

    url = configItem["url"] + "?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetProjectSettings"

    try:
        reply = urlopen(url).read()
        capabilities = parseString(reply)
        capabilities = capabilities.getElementsByTagName("WMS_Capabilities")[0]
        print("Parsing WMS GetProjectSettings of " + configItem["url"])

        topLayer = getChildElement(getChildElement(capabilities, "Capability"), "Layer")
        themeId = getChildElementValue(topLayer, "Name")

        # use name from config or fallback to WMS title
        wmsTitle = configItem.get("title") or getChildElementValue(capabilities, "Service/Title") or getChildElementValue(topLayer, "Title")

        # keywords
        keywords = []
        for keyword in getChildElement(capabilities, "Service/KeywordList").getElementsByTagName("Keyword"):
            value = getElementValue(keyword)
            if value != "infoMapAccessService":
                keywords.append(value)

        # collect WMS layers for printing
        if configItem["backgroundLayers"]:
            printLayers = [entry["printLayer"] for entry in configItem["backgroundLayers"] if "printLayer" in entry]

        # layer tree and visible layers
        layerTree = []
        visibleLayers = []
        getLayerTree(topLayer, layerTree, visibleLayers, printLayers)
        visibleLayers.reverse()

        # print templates
        printTemplates = []
        composerTemplates = getChildElement(capabilities, "Capability/ComposerTemplates")
        if composerTemplates:
            for composerTemplate in composerTemplates.getElementsByTagName("ComposerTemplate"):
                printTemplate = {
                    "name": composerTemplate.getAttribute("name")
                }
                composerMap = getChildElement(composerTemplate, "ComposerMap")
                if composerMap:
                    printTemplate["map"] = {
                        "name": composerMap.getAttribute("name"),
                        "width": float(composerMap.getAttribute("width")),
                        "height": float(composerMap.getAttribute("height"))
                    }
                composerLabels = composerTemplate.getElementsByTagName("ComposerLabel")
                labels = [composerLabel.getAttribute("name") for composerLabel in composerLabels]
                if labels:
                    printTemplate["labels"] = labels
                printTemplates.append(printTemplate)

        # drawing order
        drawingOrder = getChildElementValue(capabilities, "Capability/LayerDrawingOrder").split(",")

        # update theme config
        resultItem["id"] = themeId
        resultItem["name"] = getChildElementValue(topLayer, "Name")
        resultItem["title"] = wmsTitle
        resultItem["attribution"] = configItem["attribution"]
        resultItem["attributionUrl"] = configItem["attributionUrl"]
        resultItem["keywords"] = ", ".join(keywords)
        if "format" in configItem:
            resultItem["format"] = configItem["format"]
        if "tiled" in configItem:
            resultItem["tiled"] = configItem["tiled"]
        # use geographic bounding box for theme, as default CRS may have inverted axis order with WMS 1.3.0
        resultItem["crs"] = "EPSG:4326"
        print(getChildElementValue(topLayer, "Name"))
        if "extent" in configItem:
            resultItem["extent"] = configItem["extent"]
        else:
            resultItem["extent"] = [
                float(getChildElementValue(topLayer, "EX_GeographicBoundingBox/westBoundLongitude")),
                float(getChildElementValue(topLayer, "EX_GeographicBoundingBox/southBoundLatitude")),
                float(getChildElementValue(topLayer, "EX_GeographicBoundingBox/eastBoundLongitude")),
                float(getChildElementValue(topLayer, "EX_GeographicBoundingBox/northBoundLatitude"))
            ]
        if "scales" in configItem:
            resultItem["scales"] = configItem["scales"]
        if "printScales" in configItem:
            resultItem["printScales"] = configItem["printScales"]
        # NOTE: skip root WMS layer
        resultItem["sublayers"] = layerTree[0]["sublayers"]
        resultItem["expanded"] = True
        resultItem["backgroundLayers"] = configItem["backgroundLayers"]
        resultItem["searchProviders"] = configItem["searchProviders"]
        resultItem["additionalMouseCrs"] = configItem["additionalMouseCrs"]
        if printTemplates:
            resultItem["print"] = printTemplates
        resultItem["drawingOrder"] = drawingOrder;
        if "printLabelForSearchResult" in configItem and "print" in resultItem:
            resultItem["printLabelForSearchResult"] = configItem["printLabelForSearchResult"]

        if "watermark" in configItem:
            resultItem["watermark"] = configItem["watermark"];

        # set default theme
        if "default" in configItem or not result["themes"]["defaultTheme"]:
            result["themes"]["defaultTheme"] = resultItem["name"]

        # use first CRS for thumbnail request which is not CRS:84
        for item in topLayer.getElementsByTagName("CRS"):
            crs = getElementValue(item)
            if crs != "CRS:84":
                break
        extent = None
        for bbox in topLayer.getElementsByTagName("BoundingBox"):
            if bbox.getAttribute("CRS") == crs:
                extent = [
                    float(bbox.getAttribute("minx")),
                    float(bbox.getAttribute("miny")),
                    float(bbox.getAttribute("maxx")),
                    float(bbox.getAttribute("maxy"))
                ]
                break
        if extent:
            getThumbnail(configItem, resultItem, visibleLayers, crs, extent)

    except Exception as e:
        print("ERROR reading WMS GetProjectSettings of " + configItem["url"] + ":\n" + str(e))
        resultItem["error"] = "Could not read GetProjectSettings"
        resultItem["title"] = "Error"
        traceback.print_exc()


# recursively get themes for groups
def getGroupThemes(configGroup, resultGroup):
    for item in configGroup["items"]:
        itemEntry = {}
        getTheme(item, itemEntry)
        resultGroup["items"].append(itemEntry)

    if "groups" in configGroup:
        for group in configGroup["groups"]:
            groupEntry = {
                "title": group["title"],
                "items": [],
                "subdirs": []
            }
            getGroupThemes(group, groupEntry)
            resultGroup["subdirs"].append(groupEntry)

""" load themesConfig.json:
  {
    "themes": {
      "items": [
        {
          "url": "<http://localhost/wms/theme>",
          "title": "<Custom theme title>",            // optional, use WMS title if not set
          "thumbnail": "<filename>",                  // optional image file in assets/img/mapthumbs, if not set uses WMS GetMap to generate the thumbnail and stores it in assets/img/mapthumbs
          "attribution": "<Attribution>",             // optional theme attribution
          "attributionUrl": "<attribution URL>",      // optional theme attribution URL
          "default": true,                            // optional, set this as the initial theme
          "scales": [25000, 10000, 5000, 2500],       // optional custom map scales
          "printScales":  [25000, 10000, 5000, 2500], // optional confined set of print scales. Freely choosable if not defined.
          "extent": [xmin, ymin, xmax, ymax],         // optional custom extent which overrides extent from WMS capabilities
          "tiled": true,                              // optional, use tiled WMS (default is false)
          "format": "image/png",                      // optional, the image format to use in the WMS request, defaults to image/png
          "backgroundLayers": [                       // optional background layers
            {
              "name": "<background layer name>",      // background layer name from list below
              "printLayer": "<WMS layer name>",       // optional equivalent WMS layer name for printing
              "visibility": true                      // optional initial visibility on topic selection
            }
          ],
          "searchProviders": ["<search provider>"],   // optional search providers
          "additionalMouseCrs": ["<epsg code>"]       // optional list of additional CRS for mouse position (map projection and WGS84 are listed by default). Make sure proj defs are loaded in js/appConfig.js.
          "printLabelForSearchResult": "<labelid>"    // optional, a labelid in the print composition where to insert the label of the selected search result
          "watermark": {                              // optional, configuration of watermark to place on raster-export images
            "text": "<watermark text>",
            "texpadding": "1",                        // optional, padding between text and frame, in points
            "fontsize": "14",                         // optional, font size
            "fontfamily": "sans",                     // optional, font family
            "fontcolor": "#0000FF",                   // optional, font color
            "backgroundcolor": "#FFFFFF",             // optional, background color of the frame
            "framecolor": "#000000",                  // optional, color of the frame border
            "framewidth": 1                           // optional, width of the frame border, in pixels
          }
        }
      ],
      "groups": [                                     // optional, nested groups
        {
          "title": "<Group title>",
          "items": [
            {
              "url": "<http://localhost/wms/group_theme>"
            }
          ]
          "groups": [
            // subgroups
          ]
        }
      ],
      "backgroundLayers": [                           // optional list of background layers for themes
        {
          "name": "<background layer name>",          // referenced by themes
          "title": "<Background layer title>",
          "thumbnail": "<filename>",                  // optional image file in assets/img/mapthumbs, use default.jpg if not set
          ...                                         // layer params (excluding "group" and "visibility")
        }
      ]
    },
    "defaultScales": [50000, 25000, 10000, 5000]      // optional default map scales
  }
"""


print("Reading themesConfig.json")
with open("themesConfig.json") as fh:
    config = json.load(fh)

result = {
    "themes": {
        "title": "root",
        "subdirs": [],
        "items": [],
        "defaultTheme": None,
        "defaultScales": config["defaultScales"],
        "backgroundLayers": config["themes"]["backgroundLayers"]
    }
}
getGroupThemes(config["themes"], result["themes"])

if "backgroundLayers" in result["themes"]:
    # get thumbnails for background layers
    for backgroundLayer in result["themes"]["backgroundLayers"]:
        imgPath = "img/mapthumbs/" + backgroundLayer.get("thumbnail", "default.jpg")
        if not os.path.isfile("./assets/" + imgPath):
            imgPath = "img/mapthumbs/default.jpg"
        backgroundLayer["thumbnail"] = imgPath

# write config file
with open("./themes.json", "w") as fh:
    json.dump(result, fh, indent=2, separators=(',', ': '), sort_keys=True)
