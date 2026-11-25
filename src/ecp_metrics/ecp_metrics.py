import sys, argparse, tomllib, h5py
from pathlib import Path
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import LineString

from utils import write_geodf_to_format, write_to_excel

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


def get_od_trips(idir, timeperiods, mode_num_to_name, tp_to_ifile):
    dfs = []

    for tp in timeperiods:
        trip = h5py.File(Path(idir) / tp_to_ifile[tp])
        zones = trip['1'].shape[0]

        for mode_num, mode_name in mode_num_to_name.items():
            df = pd.DataFrame()
            df['otaz'] = np.tile(range(1,zones), zones)
            temp = pd.DataFrame.from_records(trip[str(mode_num)][:,:]).melt()
            df['dtaz'] = temp['variable'].astype(int) + 1
            df['timeperiod'] = tp
            df['mode'] = mode_name
            df['trips'] = temp['value']
            df = df.loc[df['trips'].gt(0)]
            dfs.append(df)

    return pd.concat(dfs)

def get_od_table_data(trips, timeperiods):
    table_data = {}
    for tp in ['Daily'] + timeperiods:
        table_data[tp] = {}
        for mode in ['Total','DA','SR2','SR3','TNC','COM','TRK']:
            table_name = f'{tp} {mode} Vehicle Trips'
            tp_cond = pd.Series(index=trips.index, data=True)
            mode_cond = pd.Series(index=trips.index, data=True)
            if tp != 'Daily':
                tp_cond = trips['timeperiod'].eq(tp)
            if mode != 'Total':
                mode_cond = trips['mode_simple'].eq(mode)
            df = trips.loc[tp_cond & mode_cond].pivot_table(
                index=['odist','odistname'],
                columns=['ddist','ddistname'],
                values='trips',
                aggfunc='sum'
            )
            table_data[tp][table_name] = df

    return table_data

def od(config):
    idir = Path(config['od']['idir'])
    odir = Path(config['od']['odir'])
    ofile = odir / config['od']['ofile']
    timeperiods = config['timeperiods']
    mode_num_to_name = config['od']['mode_num_to_name']
    tp_to_ifile = config['od']['tp_to_ifile']
    mode_to_simple_mode = config['od']['mode_to_simple_mode']
    template = config['od']['template']

    taz_to_dist = pd.read_csv(config['taz_to_dist'], usecols=['TAZ','DIST','DISTNAME'])

    trips = get_od_trips(
        idir=idir,
        timeperiods=timeperiods,
        mode_num_to_name=mode_num_to_name,
        tp_to_ifile=tp_to_ifile
    )

    trips = pd.merge(trips, taz_to_dist.rename(columns={'TAZ':'otaz','DIST':'odist','DISTNAME':'odistname'}))
    trips = pd.merge(trips, taz_to_dist.rename(columns={'TAZ':'dtaz','DIST':'ddist','DISTNAME':'ddistname'}))

    trips['mode_simple'] = trips['mode'].map(
        lambda x: mode_to_simple_mode[x]
    )

    table_data = get_od_table_data(trips, timeperiods)

    write_to_excel(
        template_path=template,
        output_path=ofile,
        table_data=table_data,
        first_key_is_worksheet=True
    )

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
        print('running od')
        od(config)
        
    else:
        print("Please supply a config file.")