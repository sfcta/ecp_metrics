import sys, argparse, tomllib
from pathlib import Path
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import LineString

def write_geodf_to_format(df, ofile):
    if ofile.suffix == '.csv':
        df.drop(columns='geometry').to_csv(ofile)
    if ofile.suffix == '.shp':
        df.to_file(ofile)
    if ofile.suffix == '.geojson':
        df.to_crs('epsg:4326').to_file(ofile, driver='GeoJSON')

def add_trn_dwell(trn, cap, complex_modes, tp_hours):
    trn['vehiclesPerPeriod'] = trn['FREQ'].map(lambda x: tp_hours*60.0/x)
    trn = pd.merge(trn, cap[['VEHTYPE','SimpleDelayPerStop','ConstDelayPerStop','DelayPerBoard','DelayPerAlight']])

    trn['DWELL'] = trn['SimpleDelayPerStop']
    trn.loc[trn['MODE'].isin(complex_modes),
        'DWELL'] = (trn['ConstDelayPerStop'] + 
                    trn['AB_BRDA'] * trn['DelayPerBoard']/trn['vehiclesPerPeriod'] + 
                    trn['AB_XITA'] * trn['DelayPerAlight']/trn['vehiclesPerPeriod'])
    trn.loc[trn['STOP_A'].eq(0), 'DWELL'] = 0
    trn['DWELL'] = trn['DWELL'] * 100
    trn.loc[trn['DWELL'].gt(trn['TIME']), 'DWELL'] = 0
    trn['MOVING'] = trn['TIME'] - trn['DWELL']

    return trn

def add_trn_geometry(trn, nodes, crs):
    trn = pd.merge(trn, nodes[['N','geometry']].rename(columns={'N':'A', 'geometry':'a_node'}), on='A')
    trn = pd.merge(trn, nodes[['N','geometry']].rename(columns={'N':'B', 'geometry':'b_node'}), on='B')
    trn = gpd.GeoDataFrame(data=trn.drop(['a_node','b_node','geometry'], axis=1, errors='ignore'),
                        geometry=trn.apply(lambda x: LineString([x['a_node'],x['b_node']]), axis=1),
                        crs=crs)

    return trn

def loaded_roads(config):
    idir = Path(config['loaded_roads']['idir'])
    odir = Path(config['loaded_roads']['odir'])
    timeperiods = config['timeperiods']
    tp_to_ifile = config['loaded_roads']['tp_to_ifile']
    tp_to_ofile_root = config['loaded_roads']['tp_to_ofile_root']
    output_formats = config['loaded_roads']['output_formats']
    daily_info_columns = config['loaded_roads']['daily_info_columns']
    daily_sum_columns = config['loaded_roads']['daily_sum_columns']

    freeflow = gpd.read_file(config['freeflow'], columns=['A','B','geometry']).set_crs('epsg:2227')
    freeflow = freeflow.loc[freeflow['A'].ge(4000) & freeflow['B'].ge(4000)]

    daily_dfs = []

    for tp in timeperiods:
        ifile = idir / tp_to_ifile[tp]
        if ifile.suffix == '.csv':
            df = pd.read_csv(ifile)
        elif ifile.suffix == '.dbf':
            df = gpd.read_file(ifile)

        df = pd.merge(freeflow[['A','B','geometry']], df)
        daily_dfs.append(df[daily_info_columns + daily_sum_columns + ['geometry']])

        for format in output_formats:
            write_geodf_to_format(df, odir / (tp_to_ofile_root[tp] + format))

    daily = pd.merge(
        freeflow,
        (
            pd.concat(daily_dfs)
            .groupby(daily_info_columns,as_index=False)[daily_sum_columns]
            .sum()
        ),
        on=daily_info_columns,
        how='left'
    )

    for format in output_formats:
        write_geodf_to_format(daily, odir / (tp_to_ofile_root['Daily'] + format))

def loaded_transit(conifg):
    idir = Path(config['loaded_transit']['idir'])
    odir = Path(config['loaded_transit']['odir'])
    timeperiods = config['timeperiods']
    tp_to_ifile = config['loaded_transit']['tp_to_ifile']
    tp_to_ofile_root = config['loaded_transit']['tp_to_ofile_root']
    tp_to_hours = config['tp_to_hours']
    complex_modes = config['loaded_transit']['complex_modes']
    output_formats = config['loaded_transit']['output_formats']
    daily_info_columns = config['loaded_transit']['daily_info_columns']
    daily_sum_columns = config['loaded_transit']['daily_sum_columns']

    nodes = gpd.read_file(config['nodes'], columns=['N','geometry'])

    daily_dfs = []
    for tp in timeperiods:
        f = gpd.read_file(idir / tp_to_ifile[tp])
        vehToCap = (
            pd.read_csv(idir / 'transitVehicleToCapacity.csv')
            .rename(columns={'VehicleType':'VEHTYPE'})
        )
        
        f = f.loc[f['MODE'].ge(11)]
        if len(f.loc[~f['A'].isin(nodes['N'])]) > 0:
            raise Exception('some nodes not found')

        daily_dfs.append(f[daily_info_columns + daily_sum_columns])
        # dwell and moving time
        
        f = add_trn_dwell(
            trn=f, 
            cap=vehToCap,
            complex_modes=complex_modes,
            tp_hours=tp_to_hours[tp]
        )
        
        f = add_trn_geometry(
            trn=f,
            nodes=nodes,
            crs='epsg:2227'
        )

        for format in output_formats:
            write_geodf_to_format(f, odir / (tp_to_ofile_root[tp] + format))

    daily = (
        pd.concat(daily_dfs)
        .groupby(daily_info_columns,as_index=False)[daily_sum_columns]
        .sum()
    )
    daily = add_geometry(
        trn=daily,
        nodes=nodes,
        crs='epsg:2227'
    )

    for format in output_formats:
        write_geodf_to_format(daily, odir / (tp_to_ofile_root['Daily'] + format))

if __name__=='__main__':
    parser = argparse.ArgumentParser(description="Process TOML configuration file for validation.")
    parser.add_argument("config_path", type=str, help="Path to the TOML configuration file.")
    
    # Check if the script is running in an interactive environment or not
    if len(sys.argv) > 1:
        # Running from command line, use the provided argument
        args = parser.parse_args()
        
        # Load the TOML configuration file
        config = tomllib.load(open(args.config_path, 'rb'))

        # Run the validation function with the loaded configuration
        print('running loaded_roads')
        loaded_roads(config)
        print('running loaded_transit')
        loaded_transit(config)
        
    else:
        print("Please supply a config file.")