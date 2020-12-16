import pandas as pd
import geopandas as gpd
import tkinter as tk
from tkinter import filedialog, simpledialog
import matplotlib.pyplot as plt
import os



def read_in_datasets(msg):
    ##opens a window so user can select file
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(title=msg)
    return file_path


def buffer_roads(gdf, dist):
    ## adds index column for future joins (mirrors feature id)
    gdf = gdf.reset_index()
    gdf = gdf[['index', 'geometry']]

    ## switching crs to WGS84 pseudomercator with units in meters
    gdf = gdf[gdf.geometry != None]
    gdf = gdf.set_crs(epsg=4326)
    gdf = gdf.to_crs(epsg=3857)

    ## buffering roads by dist meters
    gdf['geometry'] = gdf['geometry'].buffer(distance=dist)
    return gdf


def overlap_analysis(gdf1, gdf2):
    ## calculates dataframe with all intersection polygons between gdf1 and gdf2, then calculate area of each polygon
    intersection = gpd.overlay(gdf1, gdf2, how='intersection')
    #intersection['overlap_area'] = intersection.area

    ## drops the geometry, then groups by index number to calculate intersection per feature
    precision = intersection[['index_1', 'geometry']]
    precision = precision.dissolve(by='index_1')
    precision['overlap_area'] = precision.area
    precision = precision.reset_index()
    precision = precision.rename(columns={'index_1':'index'})
    precision = precision[['index', 'overlap_area']]

    recall = intersection[['index_2', 'geometry']]
    recall = recall.dissolve(by='index_2')
    recall['overlap_area'] = recall.area
    recall = recall.reset_index()
    recall = recall.rename(columns={'index_2':'index'})
    recall = recall[['index', 'overlap_area']]

    return precision, recall

def create_thresholds(buff, overlap, key):
    ## calculates the intersection area / total area
    buff['area'] = buff.area
    joined = buff.join(overlap.set_index('index'), on='index')
    joined.overlap_area.fillna(0, inplace=True)
    joined['prop'] = joined['overlap_area'] / joined['area']

    count = []
    area = []

    #calculates precision or recall (key) based on proportion of intersection / total area
    thresholds=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.999]
    feat_count = joined.shape[0]
    total_area = joined['area'].sum()

    for thresh in thresholds:
        count.append( joined[joined.prop > thresh].count()['index'] / feat_count )
        area.append( joined[joined.prop > thresh].sum()['area'] / total_area )

    df = pd.DataFrame(list(zip(thresholds, count, area)),
                      columns = ['threshold', key +'_count', key + '_area'])


    return joined, df, joined

def create_graphs(df, loc):

    ##precision
    plt.plot('threshold', 'precision_area', data=df, marker = '', color='skyblue', linewidth=2, label='Area')
    plt.plot('threshold', 'precision_count', data=df, marker='', color='blue', linewidth=2, label='Feature Count')
    plt.title('Precision', fontsize=14)
    plt.xlabel('Threshold', fontsize=14)
    plt.ylabel('Precision', fontsize=14)
    plt.grid(True)
    plt.legend()
    plt.savefig(os.path.join(loc, 'precision.png'))
    plt.close()

    ##recall
    plt.plot('threshold', 'recall_area', data=df, marker='', color='skyblue', linewidth=2, label='Area')
    plt.plot('threshold', 'recall_count', data=df, marker='', color='blue', linewidth=2, label="Feature Count")
    plt.title('Recall', fontsize=14)
    plt.xlabel('Threshold', fontsize=14)
    plt.ylabel('Recall', fontsize=14)
    plt.grid(True)
    plt.legend()
    plt.savefig(os.path.join(loc, 'recall.png'))

    return

def create_summary_stats(dfs_list, loc):

    ##creates and saves out summary table describing data
    rows = [[" ", "Test Data", "Reference Data"], ["Number of Features"], ["Total Area of Features"],
            ["Total Overlap Area"], ["Total Overlap/Total Area"],
             ["Median (Overlap / Total Area)"], ["Mean (Overlap / Total Area)"]]
    for df in dfs_list:
        rows[1].append(df['index'].count())
        rows[2].append(df['area'].sum())
        rows[3].append(df['overlap_area'].sum())
        rows[4].append(df['overlap_area'].sum() / df['area'].sum())
        rows[5].append(df['prop'].median())
        rows[6].append(df['prop'].mean())


    df = pd.DataFrame(rows[1:7], columns=rows[0])
    df.to_csv(os.path.join(loc, 'summary_stats.csv'))

    return




def brains():
    # choose test and reference dataset
    test_loc = read_in_datasets("Choose test dataset")
    ref_loc = read_in_datasets("Choose reference dataset")
    # ask user for buffer (with recommendation of 5 or 10 meters)
    application_window = tk.Tk()
    buf = simpledialog.askstring("Input",
                                 "Enter your road buffer in meters as an integer (Recommend 5 for same imagery or 10 for different imagery.)",
                                 parent=application_window)
    # ask user for saved directory
    out = filedialog.askdirectory(title = "Chose directory to save outputs.", parent=application_window)

    # open datasets
    test = gpd.read_file(test_loc)
    ref = gpd.read_file(ref_loc)

    # reprojects to epsg:3857 and buffers by user input
    test_buf = buffer_roads(test, int(buf))
    ref_buf = buffer_roads(ref, int(buf))

    # calculates the intersection polygons and groups them by feature index
    precision_overlap, recall_overlap = overlap_analysis(test_buf, ref_buf)

    #generates the threshold tables for precision and recall
    precision_features, precision, test_data = create_thresholds(test_buf, precision_overlap, 'precision')
    recall_features, recall, reference_data = create_thresholds(ref_buf, recall_overlap, 'recall')

    #Merges precision and recall threshold df saves out raw data and thresholds
    results = precision.join(recall.set_index('threshold'), on='threshold')
    results.to_csv(os.path.join(out, 'results.csv'))

    ##generates graphs
    create_graphs(results, out)
    create_summary_stats([test_data, reference_data], out)
    test_data.to_file(os.path.join(out, "test_data.geojson"), driver='GeoJSON')
    reference_data.to_file(os.path.join(out, "reference_data.geojson"), driver='GeoJSON')



brains()