import pandas as pd
import geopandas as gpd
import tkinter as tk
from tkinter import filedialog
import matplotlib.pyplot as plt
import os
import sys
import getopt
import numpy as np


def read_in_datasets(msg):
    ##opens a window so user can select file
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(title=msg)
    return file_path


def reproject(gdf, height):
    ## adds index column for future joins (mirrors feature id)
    gdf = gdf.reset_index()
    if height == 1:
        gdf = gdf[['index', 'geometry', 'height']]
    else:
        gdf = gdf[['index', 'geometry']]

    ## switching crs to WGS84 pseudomercator with units in meters
    gdf = gdf[gdf.geometry != None]
    gdf = gdf.set_crs(epsg=4326)
    gdf = gdf.to_crs(epsg=3857)
    gdf['area'] = gdf.area

    return gdf


def overlap_analysis_floor(gdf1, gdf2):
    # calculates dataframe with all intersection polygons between gdf1 and gdf2, then calculate area of each polygon
    intersection = gpd.overlay(gdf1, gdf2, how='intersection')
    intersection["intersect_area"] = intersection.area
    intersection['union_area'] = intersection.area_1 + intersection.area_2 - intersection.intersect_area
    
    idx = intersection.groupby(['index_1'])['intersect_area'].transform(max) == intersection['intersect_area']
    intersection_prec = intersection[idx]
    intersection_prec['iou'] = intersection.intersect_area / intersection.union_area
    
    idx2 = intersection.groupby(['index_2'])['intersect_area'].transform(max) == intersection['intersect_area']
    intersection_rec = intersection[idx2]
    intersection_rec['iou'] = intersection.intersect_area / intersection.union_area
    

    # drops the geometry, then groups by index number to calculate intersection per feature
    precision = gdf1.merge(intersection_prec[['index_1', 'intersect_area', 'iou']], left_on='index', right_on='index_1',
                           how='left')
    precision = precision.drop(columns=['index_1'])
    precision['iou'] = precision['iou'].replace(np.nan, 0)
    precision = precision[['index', 'iou', 'area']]

    recall = gdf2.merge(intersection_rec[['index_2', 'iou', 'intersect_area']], left_on='index', right_on='index_2',
                        how='left')
    recall = recall.drop(columns=['index_2'])
    recall['iou'] = recall['iou'].replace(np.nan, 0)
    recall['prop'] = recall['intersect_area'] / recall.area
    recall = recall[['index', 'iou', 'area']]

    return precision, recall, intersection_rec


def overlap_analysis_ceil(gdf1, gdf2):
    # calculates dataframe with all intersection polygons between gdf1 and gdf2, then calculate area of each polygon
    overlap = gpd.overlay(gdf1, gdf2, how='intersection')

    precision = overlap[['index_1', 'geometry']]
    precision = precision.dissolve(by='index_1')
    precision['overlap_area'] = precision.area
    precision = precision.reset_index()
    precision = precision.rename(columns={'index_1':'index'})
    precision = precision[['index', 'overlap_area']]
    
    ## calculates the intersection area / total area
    prec = gdf1.join(precision.set_index('index'), on='index')
    prec.overlap_area.fillna(0, inplace=True)
    prec['iou'] = prec['overlap_area'] / prec['area']
    prec = prec[['index', 'iou', 'area']]

    recall = overlap[['index_2', 'geometry']]
    recall = recall.dissolve(by='index_2')
    recall['overlap_area'] = recall.area
    recall = recall.reset_index()
    recall = recall.rename(columns={'index_2': 'index'})
    recall = recall[['index', 'overlap_area']]
    
    rec = gdf2.join(recall.set_index('index'), on='index')
    rec.overlap_area.fillna(0, inplace=True)
    rec['iou'] = rec['overlap_area'] / prec['area']
    rec = rec[['index', 'iou', 'area']]   

    return prec, rec


def height_metrics(gdf, ref):
    gdf['height_1'] = pd.to_numeric(gdf['height_1'])
    gdf['height_2'] = pd.to_numeric(gdf['height_2'])
    h = gdf[['index_1', 'index_2', 'height_1', 'height_2', 'iou']]
    height = ref[['index', 'height']].merge(h, left_on='index', right_on='index_2', how='left')
    height = height.fillna(0)
    height['rss'] = abs(height['height_1'] - height['height_2']) ** 2
    height['tss'] = abs(height['height_2'] - height['height_2'].mean()) ** 2

    rmse = []
    r2 = []
    count = []

    thresholds = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.999]
    feat_count = height.shape[0]

    for thresh in thresholds:
        r = height[height.iou > thresh]
        res = r['rss'].sum()
        rmse.append((res / feat_count) ** (1 / 2))

        total = r['tss'].sum()
        r2.append((1 - res / total))
        count.append(r.shape[0])
    df = pd.DataFrame(list(zip(thresholds, rmse, r2, count)),
                      columns=['threshold', 'RMSE', 'R^2', 'count'])

    return df


def height_results(df, loc):
    df.to_csv(os.path.join(loc, 'height_results.csv'))

    plt.plot('threshold', 'RMSE', data=df, marker='', color='skyblue', linewidth=2)
    plt.title('Root Mean Square Error', fontsize=14)
    plt.xlabel('Threshold', fontsize=14)
    plt.ylabel('RMSE', fontsize=14)
    plt.grid(True)
    plt.savefig(os.path.join(loc, 'rmse.png'))
    plt.close()

    plt.plot('threshold', 'R^2', data=df, marker='', color='skyblue', linewidth=2)
    plt.title('R^2', fontsize=14)
    plt.xlabel('Threshold', fontsize=14)
    plt.ylabel('R^2', fontsize=14)
    plt.grid(True)
    plt.savefig(os.path.join(loc, 'r2.png'))
    plt.close()

    return


def create_thresholds(gdf, key):
    count = []
    area = []

    # calculates precision or recall (key) based on proportion of intersection / total area (ceiling) or iou (floor)
    thresholds = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.999]
    feat_count = gdf.shape[0]
    total_area = gdf['area'].sum()

    for thresh in thresholds:
        count.append(gdf[gdf.iou > thresh].count()['index'] / feat_count)
        area.append(gdf[gdf.iou > thresh].sum()['area'] / total_area)

    df = pd.DataFrame(list(zip(thresholds, count, area)),
                      columns=['threshold', key + '_count', key + '_area'])

    return df


def create_graphs(df, loc, key):
    ##precision
    plt.plot('threshold', 'precision_' + key + '_area', data=df, marker='', color='skyblue', linewidth=2, label='Area')
    plt.plot('threshold', 'precision_' + key + '_count', data=df, marker='', color='blue', linewidth=2, label='Feature Count')
    plt.title('Precision' + key, fontsize=14)
    plt.xlabel('Threshold', fontsize=14)
    plt.ylabel('Precision', fontsize=14)
    plt.grid(True)
    plt.legend()
    plt.savefig(os.path.join(loc, key + '_precision.png'))
    plt.close()

    ##recall
    plt.plot('threshold', 'recall_' + key + '_area', data=df, marker='', color='skyblue', linewidth=2, label='Area')
    plt.plot('threshold', 'recall_' + key + '_count', data=df, marker='', color='blue', linewidth=2, label="Feature Count")
    plt.title('Recall' + key, fontsize=14)
    plt.xlabel('Threshold', fontsize=14)
    plt.ylabel('Recall', fontsize=14)
    plt.grid(True)
    plt.legend()
    plt.savefig(os.path.join(loc, key + '_recall.png'))

    return


def create_summary_stats(dfs_list, loc):
    ##creates and saves out summary table describing data
    rows = [[" ", "Test Data Ceiling", "Test Data Floor", "Reference Data Ceiling", "Reference Data Floor"], ["Number of Features"], ["Total Area of Features"], ["Mean IoU"], ["Median IoU"]]
    for df in dfs_list:
        rows[1].append(df['index'].count())
        rows[2].append(df['area'].sum())
        rows[3].append(df['iou'].mean())
        rows[4].append(df['iou'].median())

    df = pd.DataFrame(rows[1:], columns=rows[0])
    df.to_csv(os.path.join(loc, 'summary_stats.csv'))

    return


def brains(test_loc, ref_loc, out):

    # open datasets
    test = gpd.read_file(test_loc)
    ref = gpd.read_file(ref_loc)

    # looking to see if both datasets have a "height" column to calculate rmse and r2
    if 'height' in set(test.columns).intersection(set(ref.columns)):
        height = 1
    else:
        height = 0

    # reprojects to epsg:3857 and buffers by user input
    test_buf = reproject(test, height)
    ref_buf = reproject(ref, height)

    # calculates the intersection polygons and groups them by feature index
    precision_overlap_c, recall_overlap_c = overlap_analysis_ceil(test_buf, ref_buf)
    precision_overlap_f, recall_overlap_f, intersection = overlap_analysis_floor(test_buf, ref_buf)


    if height == 1:
        height = height_metrics(intersection, ref_buf)
        height_results(height, out)

    # generates the threshold tables for precision and recall
    precision_floor = create_thresholds(precision_overlap_f, 'precision_floor')
    recall_floor = create_thresholds(recall_overlap_f, 'recall_floor')

    precision_ceil = create_thresholds(precision_overlap_c, 'precision_ceiling')
    recall_ceil = create_thresholds(recall_overlap_c, 'recall_ceiling')

    # Merges precision and recall threshold df saves out raw data and thresholds
    results_floor = precision_floor.join(recall_floor.set_index('threshold'), on='threshold')
    results_floor.to_csv(os.path.join(out, 'results_floor.csv'))

    results_ceil = precision_ceil.join(recall_ceil.set_index('threshold'), on='threshold')
    results_ceil.to_csv(os.path.join(out, 'results_ceiling.csv'))

    ## generates graphs
    create_graphs(results_floor, out, 'floor')
    create_graphs(results_ceil, out, 'ceiling')
    create_summary_stats([precision_overlap_c, precision_overlap_f, recall_overlap_c, recall_overlap_f], out)



# a simple alteration can enable command line options
# uncomment the commented lines below then comment out the bottom lines

# def main(argv):
#     try:
#         opts, args = getopt.getopt(argv, "t:r:o:h")
#         for opt, arg in opts:
#             if opt == "-t":
#                 test_loc = arg
#             elif opt == "-r":
#                 ref_loc = arg
#             elif opt == "-o":
#                 out = arg
#             elif opt == '-h':
#                 print(r'python building_eval.py -t \path\to\test\file -r \path\to\ref\file -o \path\to\output\dir')
#                 sys.exit()
#
#   brains(test_loc, ref_loc, out)
#
# if __name__ == "__main__":
#     main(sys.argv[1:])


test_loc = read_in_datasets("Choose test dataset")
ref_loc = read_in_datasets("Choose reference dataset")
application_window = tk.Tk()
out = filedialog.askdirectory(title="Chose directory to save outputs.", parent=application_window)
brains(test_loc, ref_loc, out)
