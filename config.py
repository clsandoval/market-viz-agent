import os, requests, chainlit as cl
import pandas as pd
import pydeck as pdk
from dotenv import load_dotenv

load_dotenv()

ASSISTANT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_google_maps",
            "description": "Research google map points of interest given a query and a latitude/longitude coordinate",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "A query to search for (ex. Fast Food in Metro Manila)",
                    },
                    "latitude": {
                        "type": "string",
                        "description": "latitude coordinate",
                    },
                    "longitude": {
                        "type": "string",
                        "description": "longitude coordinate",
                    },
                },
                "required": ["query", "latitude", "longitude"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "visualize_on_map",
            "description": "Plot map data on a folium figure",
            "parameters": {
                "type": "object",
                "properties": {
                    "map_data": {
                        "type": "array",
                        "description": "A dataset to plot on a map",
                        "items": {
                            "type": "object",
                            "properties": {
                                "latitude": {
                                    "type": "string",
                                    "description": "Latitude coordinate of the point",
                                },
                                "longitude": {
                                    "type": "string",
                                    "description": "Longitude coordinate of the point",
                                },
                                "value": {
                                    "type": "string",
                                    "description": "Float Value to plot at the point, Only used if the visualization wanted is a heatmap",
                                },
                            },
                            "required": ["latitude", "longitude", "value"],
                        },
                    }
                },
                "required": ["map_data"],
            },
        },
    },
]


def search_google_maps(query, latitude, longitude):

    url = "https://local-business-data.p.rapidapi.com/search"

    querystring = {
        "query": query,
        "limit": "10",
        "lat": latitude,
        "lng": longitude,
        "zoom": "13",
        "language": "en",
        "extract_emails_and_contacts": "false",
    }

    headers = {
        "x-rapidapi-key": os.getenv("RAPID_API_KEY"),
        "x-rapidapi-host": "local-business-data.p.rapidapi.com",
    }

    response = requests.get(url, headers=headers, params=querystring)

    return response.json()


import folium
from folium.plugins import HeatMap


def visualize_on_map(map_data):
    if not map_data:
        return {"status": "Error", "message": "No data provided"}

    # Convert map_data to DataFrame
    df = pd.DataFrame(map_data)
    df["latitude"] = df["latitude"].astype(float)
    df["longitude"] = df["longitude"].astype(float)
    df["value"] = df["value"].astype(float)

    # Compute center location
    center_lat, center_lon = df["latitude"].mean(), df["longitude"].mean()

    # Create a Folium map centered on the mean latitude and longitude
    folium_map = folium.Map(location=[center_lat, center_lon], zoom_start=12)

    # Prepare data for heatmap
    heat_data = [
        [row["latitude"], row["longitude"], row["value"]] for _, row in df.iterrows()
    ]

    # Add heatmap to the map
    HeatMap(heat_data).add_to(folium_map)

    # Save map to HTML file
    file_path = "heatmap.html"
    folium_map.save(file_path)

    return {"status": "Heatmap Created", "file": file_path}


FUNCTION_MAP = {
    "search_google_maps": search_google_maps,
    "visualize_on_map": visualize_on_map,
}
