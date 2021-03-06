## Usage: python3.8 marco-devel.py [--rate 4096] [--verbose] [--start POSITIVE INTEGER ] [--end POSITIVE INTEGER] [--standardize] --datafile datafile.txt
## GWOSC data files must be in "Data subdirectory". Datafile.txt must be in the dame directory of this script.
##    It must contain a list of GWOSC files to be analyzed , one per line. Results go in "Results" subdirectory.
import numpy as np
import os
import sys
import pandas as pd
import argparse
import h5py
import csv
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from sklearn import metrics as metrics
from sklearn import preprocessing

parser = argparse.ArgumentParser()
parser.add_argument('--verbose', action='count', help='Verbose mode')
parser.add_argument('--datafile', help='Ascii file with list of hdf data file from GWOSC. Each line (example): H-H1_GWOSC_O2_4KHZ_R1-1181155328-4096.hdf5', required=True)
parser.add_argument('--start',  type=int, help='The start time (in seconds) of the data to analyze. For debugging purposes. (Positive integer, default = 0)', default=0, required=False)
parser.add_argument('--end',  type=int, help='The end time (in seconds) of data to analyze. For debugging purposes. (Positive integer, default = all the available time)', required=False)
parser.add_argument('--rate', type=int, help='Sampling rate (positive even integer. It must match the sampling rate of the LIGO data. Default = 4096)', default=4096, required=False)
parser.add_argument('--standardize', action='count', help='Standardize data')
args = parser.parse_args()

data_file = args.datafile
verbose = args.verbose
sampling_rate = args.rate
start_time = args.start
end_time = args.end
sampling_rate = args.rate
standardize = args.standardize

def read_strain(sampling_rate,start_time,data_download):
    end_time = start_time + 1
    data_start = sampling_rate * start_time
    data_end = sampling_rate * end_time
    time_stamps =np.arange(data_start, data_end)
    data = pd.DataFrame({'Time':time_stamps,'Strain':data_download[data_start:data_end]})
    return data

def data_download(data_file):
    currentDirectory = os.getcwd()
    listfile = currentDirectory + '/Data/' + data_file
    datafiles = pd.read_csv(currentDirectory + '/' + data_file,comment ='#',header=None)
    data_download = []
    CBC_allCATData = [] 
    for datafile in datafiles[0]:
        datafile = str(datafile)
        if verbose:
            print('Reading the data file %s sampled at %d Hz' % (datafile, sampling_rate))
        dataFile = h5py.File(currentDirectory+'/Data/'+ datafile, 'r')
        data_download = np.append(data_download,np.array(dataFile['strain/Strain'][...]))
        dqInfo = dataFile['quality']['simple']
        bitnameList = dqInfo['DQShortnames'][()]
        nbits = len(bitnameList)
        qmask = dqInfo['DQmask'][()] #0 b'DATA' #1 b'CBC_CAT1' #2 b'CBC_CAT2' #3 b'CBC_CAT3' #4 b'BURST_CAT1' #5 b'BURST_CAT2' #6 b'BURST_CAT3'
        Data = (qmask >> 0) & 1	 
        CBC_CAT1 = (qmask >> 1) & 1    #BURST_CAT1 = (qmask >> 4) & 1   
        CBC_CAT2 = (qmask >> 2) & 1    #BURST_CAT2 = (qmask >> 5) & 1
        CBC_CAT3 = (qmask >> 3) & 1    #BURST_CAT3 = (qmask >> 6) & 1

        CBC_CAT1Data = Data & CBC_CAT1    #BURST_CAT1Data = Data & BURST_CAT1
        CBC_CAT2Data = Data & CBC_CAT2    #BURST_CAT2Data = Data & BURST_CAT2
        CBC_CAT3Data = Data & CBC_CAT3    #BURST_CAT3Data = Data & BURST_CAT3

        CBC_allCATData = np.append(CBC_allCATData,CBC_CAT1Data + CBC_CAT2Data + CBC_CAT3Data)
        
        dataFile.close()
    return data_download, CBC_allCATData

#This function standardizes the data so that the mean is zero and the standard deviation is 1. Requires the dataframe made with real_data and returns the
#standrdized strain
def standardize_data(X):
    data_reshaped = np.asarray(X).reshape(-1, 1)
    scaler = StandardScaler().fit(data_reshaped)
    ####print('Mean: %f, StandardDeviation: %f' % (scaler.mean_, np.sqrt(scaler.var_)))
    normalized = scaler.transform(data_reshaped)
    ####inversed = scaler.inverse_transform(normalized)   
    return normalized

def build_training_dataset(sampling_rate,start_time,end_time,data_download,DQ):
    if verbose:
        print('Building a %d second-long training data set...' % (end_time - start_time))    
    labeled_data = pd.DataFrame(columns=['Strain', 'Label'])
    i = start_time
    while i < end_time:
        data = read_strain(sampling_rate,i,data_download)
        if np.isnan(data.Strain[0]):   #Alternative, possibly slower: if data.isnull().values.any():
            #if verbose:
            #    print('Data starting at %d second(s) is not defined. Skipping.' % (i))
            i+=1 
            continue
        X = data['Strain'].values
        if standardize:
        	X = standardize_data(X).reshape(1, -1)[0]
        labeled_data=labeled_data.append({'Time':i,'Strain':X,'Label':DQ[i]}, ignore_index=True)
        i+=1
    data_length = len(labeled_data)
    if not data_length:
        print('There is no data to train. Aborting!')
        sys.exit()
    elif data_length < (end_time - start_time):
        print('Warning: Some data is not defined. The duration of the training data set is only %d second(s).' % (len(labeled_data)))    
        
    return labeled_data

def build_training_model(dataset):
    if verbose:
        print('Building the training model...')    
   #clf = MLPClassifier(solver = 'lbfgs', alpha = 1e-5, hidden_layer_sizes = (10, 4), random_state = 1)
    clf = MLPClassifier()
    clf.fit(dataset['Strain'].to_list(), dataset['Label'].to_list())
    return clf

def save_predicted_labels(data_file,input_dataset,model):
    if verbose:
        print('Training the model...')    
    currentDirectory = os.getcwd()
    [filename_body, filename_ext] = data_file.split('.')
    filename = currentDirectory+'/Results/'+filename_body+'-prediction.txt'
    if os.path.isfile(filename):
        os.remove(filename)
    labels = model.predict(input_dataset['Strain'].to_list())
    labels_index = input_dataset['Time'].to_list()
    predicted_labels = pd.DataFrame({'Time':labels_index,'Label':labels},dtype=int)
    with open(filename, 'a') as f:
        f.write('# Predicted labels for ' + data_file + '\n')
        predicted_labels.to_csv(f,sep='\t',index=False)
    if verbose:
        print('Predicted labels are saved in ./Results/%s.' % (filename_body+'-prediction.txt'))    
    return predicted_labels

def compute_metrics(data_file,training_set,predicted_labels):
    if verbose:
        print('Calculating the prediction metrics...')    
    currentDirectory = os.getcwd()
    [filename_body, filename_ext] = data_file.split('.')
    filename = currentDirectory+'/Results/'+filename_body+'-metrics.txt'
    if os.path.isfile(filename):
        os.remove(filename)
    y_true = training_set['Label'].to_list()
    y_pred = predicted_labels['Label'].to_list()
    predicted_metrics = metrics.classification_report(y_true, y_pred, zero_division='warn')
    cm_array = metrics.confusion_matrix(y_true, y_pred)
    cm = pd.DataFrame(cm_array) 
    with open(filename, 'a') as f:
        f.write('# Predicted labels for ' + data_file + ':\n\n')
        f.write(predicted_metrics)
        f.write('\n# Confusion matrix for ' + data_file + ':\n\n')
        cm.to_csv(f,sep='\t',index=True)
    if verbose:
        print('Prediction metrics are saved in ./Results/%s.' % (filename_body+'-metrics.txt'))    
    return

#--- Body of program

if verbose:
    print('Starting!')

data, DQ = data_download(data_file)

if not end_time or end_time > len(DQ):
   end_time = len(DQ)
   print('Warning: The end time of the training set is %d second(s).' % (end_time))

training_dataset = build_training_dataset(sampling_rate,start_time,end_time,data,DQ)
trained_model = build_training_model(training_dataset)
DQ_predicted = save_predicted_labels(data_file,training_dataset,trained_model)
compute_metrics(data_file,training_dataset,DQ_predicted)

if verbose:
    print('Done!')

sys.exit()
