import pandas as pd
import numpy as np
import csv
import collections
import os
pd.options.mode.chained_assignment = None  # default='warn'
import random
import subprocess
from tqdm import tqdm
import pysam

def flatten(x):
    """Flatten a nested list.

    """
    if isinstance(x, collections.Iterable):
        return [a for i in x for a in flatten(i)]
    else:
        return [x]


def cellbarcode_generator(length, size=10):
	"""Generate random cellbarcode.

    Parameters
    ----------
    length: `int`
        Number of cells.
    size: `int` (default: '10')
        Size of cell barcode. Default value is 10 bp.

    Return
    ------
    cb_list: `list`
        List of randomly generated cell barcodes.
    """
	chars = 'ACGT'
	cb_list = [''.join(random.choice(chars) for _ in range(size)) for cell in range(length)]
	return cb_list


def find_leftnearest_nonpeak(non_peak_list, gray_peak):
	"""Find the gray peak's left nearest non-peak from a non-peak list.

    """
	dist1 = np.abs(non_peak_list[:,2].astype(int) - int(gray_peak[1]))
	id = dist1.argmin()
	return id


def scATAC_GenerateBAMCoord(bed_file, count_mat_file, read_bedfile_prename, INPUT_bamfile, outdirectory, OUTPUT_cells_barcode_file, jitter_size=5, read_len=50, random_noise_mode=False, GrayAreaModeling=False):
    """Generate Synthetic reads in BED format. 

    Parameters
    ----------
    bed_file: `str`
        Input the bed file of features.
    count_mat_file: `str`
        The name of synthetic count matrix.
    read_bedfile_prename: `str`
        Specify the base name of output bed file.
    INPUT_bamfile: `str`
        Input BAM file for anlaysis.
    outdirectory: `str`
        Specify the output directory for synthetic reads bed file.
    OUTPUT_cells_barcode_file: `str`
        Specify the file name storing the synthetic cell barcodes.
    jitter_size: `int` (default: '5')
        Specify the range of random shift to avoid replicate synthetic reads. Default value is 5 bp.
    read_len: `int` (default: '50')
        Specify the length of synthetic reads. Default value is 50 bp.
    random_noise_mode: `bool` (default: 'False')
        Specify whether to use a uniform distribution of reads.
    GrayAreaModeling: `bool` (default: 'False')
        Specify whether to generate synthetic reads for Gray Areas using non-peak counts. Do not specify 'True' when generating reads for peaks.
    """
    count_mat_df = pd.read_csv("%s" % (count_mat_file), header=0, delimiter="\t")
    count_mat = count_mat_df.to_numpy()
    count_mat_cluster = count_mat_df.columns.to_numpy()
    n_cell = np.shape(count_mat)[1]
    samfile = pysam.AlignmentFile(INPUT_bamfile, "rb")
    with open(bed_file) as file:
        reader = csv.reader(file, delimiter="\t")
        open_peak = np.asarray(list(reader))
    peak_nonzero_id = np.nonzero(count_mat.sum(axis=1))[0]
    random.seed(2022)
    random_cellbarcode_list = cellbarcode_generator(n_cell, size=16)
    with open(OUTPUT_cells_barcode_file, 'w') as f:
        for item in random_cellbarcode_list:
            f.write(item + "\n")
    cellbarcode_list_withclusters = np.vstack((random_cellbarcode_list, count_mat_cluster)).transpose()
    with open(OUTPUT_cells_barcode_file + ".withSynthCluster", 'w') as f:
        for item in cellbarcode_list_withclusters:
            f.write("\t".join(item) + "\n")
    # Create read 1 and read 2 files
    with open("%s/%s.read1.bed" % (outdirectory, read_bedfile_prename), 'w') as f_1:
        pass
    with open("%s/%s.read2.bed" % (outdirectory, read_bedfile_prename), 'w') as f_2:
        pass
    print("[scReadSim] Generating Synthetic Reads for Feature Set: %s" % (bed_file))
    for relative_peak_ind in tqdm(range(len(peak_nonzero_id))):
        peak_ind = peak_nonzero_id[relative_peak_ind]
        rec = open_peak[peak_ind]
        rec_name = '_'.join(rec)
        reads = samfile.fetch(rec[0], int(rec[1]), int(rec[2]))
        # tic = time.time()
        # Extract read information
        reads_str = []
        for read in reads:
            if read.is_reverse==1:
                strand = -1
            else:
                strand = 1
            if read.is_read1==1:
                read_order = 1
            else:
                read_order = 2
            start = read.reference_start
            mate_start = read.next_reference_start
            read_len_cur = read.query_alignment_length
            read_info = [start, mate_start, read_len_cur, read_order, strand]
            reads_str.append(read_info)
        if len(reads_str) > 0: # If no real reads exist in the peak, skip
            count_vec = count_mat[peak_ind,:] # Synthetic umi count
            count_frag_vec = np.ceil(count_vec/2).astype(int)
            npair_read_synthetic = np.sum(count_frag_vec).astype(int) # nrow(reads_cur) should equal to nfrag_cur
            # npair_read_synthetic = np.ceil(np.sum(count_vec)/2).astype(int) # total number of synthetic reads
            read_sampled_unsplit = np.array(reads_str)[np.random.choice(len(reads_str), size=npair_read_synthetic, replace=True),:]
            # Sample starting position if random noise mode is on, or use real read starting position
            if random_noise_mode == True:
                read_synthetic_start = np.random.randint(int(rec[1]), int(rec[2]), size=npair_read_synthetic)
            else:
                read_synthetic_start = read_sampled_unsplit[:,0].astype(int)
            # Generate Read Name
            nonempty_cell_ind = np.where(count_frag_vec != 0)[0]
            target_peak_concat = rec[0] + ":" + str(rec[1]) + "-" + str(rec[2])
            read_name_list = [random_cellbarcode_list[nonempty_cell_ind[ind]] + "CellNo" + str(nonempty_cell_ind[ind] + 1) + ":" + str(target_peak_concat) + "#" + str(count).zfill(4) for ind in range(len(nonempty_cell_ind)) for count in range(count_frag_vec[nonempty_cell_ind[ind]])]
            # Create dataframe for unspiltted sampled reads
            reads_cur = pd.DataFrame({
                'chr': rec[0],
                'r_start': read_synthetic_start,
                'mate_start': read_sampled_unsplit[:,1].astype(int) + read_synthetic_start - read_sampled_unsplit[:,0].astype(int),
                'read_name': read_name_list,
                'length': read_sampled_unsplit[:,2],
                'read_order': read_sampled_unsplit[:,3].astype(int),
                'strand': read_sampled_unsplit[:,4].astype(int),
                'mate_strand': -read_sampled_unsplit[:,4].astype(int)
                })
            contain_read_indicator = read_sampled_unsplit[:,0] == read_sampled_unsplit[:,1]
            reads_cur['read_length'] = read_len
            reads_cur['read_length'][contain_read_indicator] = abs(reads_cur['length'].astype(int)[contain_read_indicator])
            # Add jitter size to read positions
            jitter_value_vec = np.random.randint(-jitter_size,jitter_size,size=npair_read_synthetic).astype(int)  # nrow(reads_cur) should equal to nfrag_cur
            reads_cur['r_start_shifted'] = reads_cur['r_start'].astype(int)  + jitter_value_vec
            reads_cur['mate_start_shifted'] = reads_cur['mate_start'].astype(int)  + jitter_value_vec
            reads_cur['r_end_shifted'] = reads_cur['r_start'].astype(int) + reads_cur['read_length'].astype(int) + jitter_value_vec
            reads_cur['mate_end_shifted'] = reads_cur['mate_start'].astype(int) + reads_cur['read_length'].astype(int) + jitter_value_vec
            # Split read 1 and read 2
            read_1_df = pd.concat([reads_cur.loc[reads_cur['read_order'] == 1, ['chr','r_start_shifted', 'r_end_shifted', 'read_length', 'strand']].rename(columns={'r_start_shifted':'r1_start_shifted', 'r_end_shifted':'r1_end_shifted'}), reads_cur.loc[reads_cur['read_order'] == 2, ['chr','mate_start_shifted', 'mate_end_shifted', 'read_length', 'mate_strand']].rename(columns={'mate_start_shifted':'r1_start_shifted', 'mate_end_shifted':'r1_end_shifted', 'mate_strand': 'strand'})], ignore_index=True)
            read_2_df = pd.concat([reads_cur.loc[reads_cur['read_order'] == 1, ['chr','mate_start_shifted', 'mate_end_shifted', 'read_length', 'mate_strand']].rename(columns={'mate_start_shifted':'r2_start_shifted', 'mate_end_shifted':'r2_end_shifted', 'mate_strand': 'strand'}), reads_cur.loc[reads_cur['read_order'] == 2, ['chr','r_start_shifted', 'r_end_shifted', 'read_length', 'strand']].rename(columns={'r_start_shifted':'r2_start_shifted', 'r_end_shifted':'r2_end_shifted'}), ], ignore_index=True)
            read_1_df['read_name'] = read_name_list
            read_2_df['read_name'] = read_name_list
            # read_1_df['read_length'] = read_len
            # read_2_df['read_length'] = read_len
            read_1_df['strand'] = ['+' if x == 1  else '-' for x in read_1_df['strand']]
            read_2_df['strand'] = ['+' if x == 1  else '-' for x in read_2_df['strand']]
            read_1_df_order = read_1_df[['chr','r1_start_shifted', 'r1_end_shifted', 'read_name', 'read_length', 'strand']]
            read_2_df_order = read_2_df[['chr','r2_start_shifted', 'r2_end_shifted', 'read_name', 'read_length', 'strand']]
            if read_1_df_order.shape[0] != read_2_df_order.shape[0]:
                print("[Warning] Peak %s read 1 and read 2 not identical!", relative_peak_ind)
            if np.sum(np.array(read_1_df_order[['r1_start_shifted']] < 0)) + np.sum(np.array(read_2_df_order[['r2_start_shifted']] < 0)) > 0:
                print("[Warning] Synthetic read pair for Peak %s %s has read 1 or read 2 start position negative: synthetic read pair removed!" % (relative_peak_ind, rec_name))
                ind_preserve = np.array(read_1_df_order[['r1_start_shifted']] >= 0) * np.array(read_2_df_order[['r2_start_shifted']] >= 0) # Remove rows with read 1 or read 2's start position negative
                read_1_df_order_removeNegRead = read_1_df_order.loc[ind_preserve]
                read_2_df_order_removeNegRead = read_2_df_order.loc[ind_preserve]
            else:
                read_1_df_order_removeNegRead = read_1_df_order
                read_2_df_order_removeNegRead = read_2_df_order
            read_1_df_order_removeNegRead.to_csv("%s/%s.read1.bed" % (outdirectory, read_bedfile_prename), header=None, index=None, sep='\t', mode='a')
            read_2_df_order_removeNegRead.to_csv("%s/%s.read2.bed" % (outdirectory, read_bedfile_prename), header=None, index=None, sep='\t', mode='a')
            if npair_read_synthetic != read_1_df_order_removeNegRead.shape[0]:
                print("Target read pair %s | Sample synthetic read pair %s" % (npair_read_synthetic, read_1_df_order_removeNegRead.shape[0]))
    print("\n[scReadSim] Created:")
    print("[scReadSim] Read 1 bed file: %s/%s.read1.bed" % (outdirectory, read_bedfile_prename))
    print("[scReadSim] Read 2 bed file: %s/%s.read2.bed" % (outdirectory, read_bedfile_prename))
    # Modeling Gray Areas
    if GrayAreaModeling == True:
        print("\n[scReadSim] Generating reads for Gray Area...")
        # If gray area bed file not found, pring the error.
        try:
            with open(outdirectory + "/" + "scReadSim.grayareas.bed") as file:
                reader = csv.reader(file, delimiter="\t")
                GreyArea_set = np.asarray(list(reader))
        except Exception as e:
            print("[Error] Gray Area Bed File not Found: %s" % (outdirectory, scReadSim.grayareas.bed))
        with open("%s/GrayArea_Assigned_Synthetic_CountMatrix.txt" % outdirectory, 'w') as f_2:
            pass
        # Create read 1 and read 2 files
        with open("%s/%s.GrayArea.read1.bed" % (outdirectory, read_bedfile_prename), 'w') as f_1:
            pass
        with open("%s/%s.GrayArea.read2.bed" % (outdirectory, read_bedfile_prename), 'w') as f_2:
            pass
        random.seed(2022)
        for peak_id in tqdm(range(len(GreyArea_set))):
            grey_area = GreyArea_set[peak_id]
            rec_name = '_'.join(grey_area)
            grey_length = int(grey_area[2]) - int(grey_area[1])
            idx = find_leftnearest_nonpeak(open_peak, grey_area)
            nonpeak_cur_count = count_mat[idx,:]
            nonpeak_cur_length = int(open_peak[idx,2]) - int(open_peak[idx,1])
            if np.sum(nonpeak_cur_count) == 0:
                grey_count_vec = pd.DataFrame(np.zeros(n_cell, dtype=int)).T
                grey_count_vec.to_csv("%s/GrayArea_Assigned_Synthetic_CountMatrix.txt" % outdirectory, header=None, index=None, sep='\t', mode='a')
                continue # print zero counts for grey area if no reads in non-peak count mat
            # scaled_grey_count = np.round(nonpeak_cur_count * grey_length / nonpeak_cur_length).astype(int)
            scaled_grey_count = nonpeak_cur_count * np.random.binomial(1, min(grey_length / nonpeak_cur_length, 1), len(nonpeak_cur_count))
            # Write out grey area synthetic count matrix (optional)
            grey_count_vec = pd.DataFrame(np.append(rec_name, scaled_grey_count)).T
            grey_count_vec.to_csv("%s/GrayArea_Assigned_Synthetic_CountMatrix.txt" % outdirectory, header=None, index=None, sep='\t', mode='a')
            if np.sum(scaled_grey_count) == 0:
                continue # if no synthetic count for grey then skip the peak 
            reads = samfile.fetch(grey_area[0], int(grey_area[1]), int(grey_area[2]))
            # Extract read information
            reads_str = []
            for read in reads:
                if read.is_reverse==1:
                    strand = -1
                else:
                    strand = 1
                if read.is_read1==1:
                    read_order = 1
                else:
                    read_order = 2
                start = read.reference_start
                mate_start = read.next_reference_start
                read_len_cur = read.query_alignment_length
                read_info = [start, mate_start, read_len_cur, read_order, strand]
                reads_str.append(read_info)
            if len(reads_str) == 0: # If no real reads exist in the peak, skip
                continue
            count_frag_vec = np.ceil(scaled_grey_count/2).astype(int)
            npair_read_synthetic = np.sum(count_frag_vec).astype(int) # nrow(reads_cur) should equal to nfrag_cur
            read_sampled_unsplit = np.array(reads_str)[np.random.choice(len(reads_str), size=npair_read_synthetic, replace=True),:]
            # Sample starting position if random noise mode is on, or use real read starting position
            if random_noise_mode == True:
                read_synthetic_start = np.random.randint(int(grey_area[1]), int(grey_area[2]), size=npair_read_synthetic)
            else:
                read_synthetic_start = read_sampled_unsplit[:,0].astype(int)
            # Generate Read Name
            nonempty_cell_ind = np.where(count_frag_vec != 0)[0]
            target_peak_concat = grey_area[0] + ":" + str(grey_area[1]) + "-" + str(grey_area[2])
            read_name_list = [random_cellbarcode_list[nonempty_cell_ind[ind]] + "CellNo" + str(nonempty_cell_ind[ind] + 1) + ":" + str(target_peak_concat) + "#" + str(count).zfill(4) for ind in range(len(nonempty_cell_ind)) for count in range(count_frag_vec[nonempty_cell_ind[ind]])]
            # Create dataframe for unspiltted sampled reads
            reads_cur = pd.DataFrame({
                'chr': grey_area[0],
                'r_start': read_synthetic_start,
                'mate_start': read_sampled_unsplit[:,1].astype(int) + read_synthetic_start - read_sampled_unsplit[:,0].astype(int),
                'read_name': read_name_list,
                'length': read_sampled_unsplit[:,2],
                'read_order': read_sampled_unsplit[:,3].astype(int),
                'strand': read_sampled_unsplit[:,4].astype(int),
                'mate_strand': -read_sampled_unsplit[:,4].astype(int)
                })
            contain_read_indicator = read_sampled_unsplit[:,0] == read_sampled_unsplit[:,1]
            reads_cur['read_length'] = read_len
            reads_cur['read_length'][contain_read_indicator] = abs(reads_cur['length'].astype(int)[contain_read_indicator])
            # Add jitter size to read positions
            jitter_value_vec = np.random.randint(-jitter_size,jitter_size,size=npair_read_synthetic).astype(int)  # nrow(reads_cur) should equal to nfrag_cur
            reads_cur['r_start_shifted'] = reads_cur['r_start'].astype(int)  + jitter_value_vec
            reads_cur['mate_start_shifted'] = reads_cur['mate_start'].astype(int)  + jitter_value_vec
            reads_cur['r_end_shifted'] = reads_cur['r_start'].astype(int) + reads_cur['read_length'].astype(int) + jitter_value_vec
            reads_cur['mate_end_shifted'] = reads_cur['mate_start'].astype(int) + reads_cur['read_length'].astype(int) + jitter_value_vec
            # Split read 1 and read 2
            read_1_df = pd.concat([reads_cur.loc[reads_cur['read_order'] == 1, ['chr','r_start_shifted', 'r_end_shifted', 'read_length', 'strand']].rename(columns={'r_start_shifted':'r1_start_shifted', 'r_end_shifted':'r1_end_shifted'}), reads_cur.loc[reads_cur['read_order'] == 2, ['chr','mate_start_shifted', 'mate_end_shifted', 'read_length', 'mate_strand']].rename(columns={'mate_start_shifted':'r1_start_shifted', 'mate_end_shifted':'r1_end_shifted', 'mate_strand': 'strand'})], ignore_index=True)
            read_2_df = pd.concat([reads_cur.loc[reads_cur['read_order'] == 1, ['chr','mate_start_shifted', 'mate_end_shifted', 'read_length', 'mate_strand']].rename(columns={'mate_start_shifted':'r2_start_shifted', 'mate_end_shifted':'r2_end_shifted', 'mate_strand': 'strand'}), reads_cur.loc[reads_cur['read_order'] == 2, ['chr','r_start_shifted', 'r_end_shifted', 'read_length', 'strand']].rename(columns={'r_start_shifted':'r2_start_shifted', 'r_end_shifted':'r2_end_shifted'}), ], ignore_index=True)
            read_1_df['read_name'] = read_name_list
            read_2_df['read_name'] = read_name_list
            # read_1_df['read_length'] = read_len
            # read_2_df['read_length'] = read_len
            read_1_df['strand'] = ['+' if x == 1  else '-' for x in read_1_df['strand']]
            read_2_df['strand'] = ['+' if x == 1  else '-' for x in read_2_df['strand']]
            read_1_df_order = read_1_df[['chr','r1_start_shifted', 'r1_end_shifted', 'read_name', 'read_length', 'strand']]
            read_2_df_order = read_2_df[['chr','r2_start_shifted', 'r2_end_shifted', 'read_name', 'read_length', 'strand']]
            if read_1_df_order.shape[0] != read_2_df_order.shape[0]:
                print("[Warning] Gray Area %s read 1 and read 2 not identical!", peak_id)
            if np.sum(np.array(read_1_df_order[['r1_start_shifted']] < 0)) + np.sum(np.array(read_2_df_order[['r2_start_shifted']] < 0)) > 0:
                print("[Warning] Synthetic read pair for Peak %s %s has read 1 or read 2 start position negative: synthetic read pair removed!" % (peak_id, rec_name))
                ind_preserve = np.array(read_1_df_order[['r1_start_shifted']] >= 0) * np.array(read_2_df_order[['r2_start_shifted']] >= 0) # Remove rows with read 1 or read 2's start position negative
                read_1_df_order_removeNegRead = read_1_df_order.loc[ind_preserve]
                read_2_df_order_removeNegRead = read_2_df_order.loc[ind_preserve]
            else:
                read_1_df_order_removeNegRead = read_1_df_order
                read_2_df_order_removeNegRead = read_2_df_order
            read_1_df_order_removeNegRead.to_csv("%s/%s.GrayArea.read1.bed" % (outdirectory, read_bedfile_prename), header=None, index=None, sep='\t', mode='a')
            read_2_df_order_removeNegRead.to_csv("%s/%s.GrayArea.read2.bed" % (outdirectory, read_bedfile_prename), header=None, index=None, sep='\t', mode='a')
            if npair_read_synthetic != read_1_df_order_removeNegRead.shape[0]:
                print("Target read pair %s | Sample synthetic read pair %s" % (npair_read_synthetic, read_1_df_order_removeNegRead.shape[0]))
        print("\n[scReadSim] Created:")
        print("[scReadSim] Read 1 Bed File: %s/%s.GrayArea.read1.bed" % (outdirectory, read_bedfile_prename))
        print("[scReadSim] Read 2 Bed File: %s/%s.GrayArea.read2.bed" % (outdirectory, read_bedfile_prename))
        print("[scReadSim] Done.")


def scATAC_GenerateBAMCoord_OutputPeak(target_peak_assignment_file, count_mat_file, read_bedfile_prename, INPUT_bamfile, outdirectory, OUTPUT_cells_barcode_file, jitter_size=5, read_len=50, random_noise_mode = False):
    """Generate Synthetic reads in BED format. 

    Parameters
    ----------
    target_peak_assignment_file: `str`
        Mapping file between input peaks and output peaks, output by 'FeatureMapping'.
    count_mat_file: `str`
        The name of synthetic count matrix.
    read_bedfile_prename: `str`
        Specify the base name of output bed file.
    INPUT_bamfile: `str`
        Input BAM file for anlaysis.
    outdirectory: `str`
        Specify the output directory for synthetic reads bed file.
    OUTPUT_cells_barcode_file: `str`
        Specify the file name storing the synthetic cell barcodes.
    jitter_size: `int` (default: '5')
        Specify the range of random shift to avoid replicate synthetic reads. Default value is 5 bp.
    read_len: `int` (default: '50')
        Specify the length of synthetic reads. Default value is 50 bp.
    random_noise_mode: 'bool' (default: 'False')
        Specify whether to use a uniform distribution of reads.
    """
    
    count_mat_df = pd.read_csv("%s/%s" % (outdirectory, count_mat_file), header=0, delimiter="\t")
    count_mat = count_mat_df.to_numpy()
    count_mat_cluster = count_mat_df.columns.to_numpy()
    n_cell = np.shape(count_mat)[1]
    samfile = pysam.AlignmentFile(INPUT_bamfile, "rb")
    with open(target_peak_assignment_file) as open_peak:
        reader = csv.reader(open_peak, delimiter="\t")
        open_peak = np.asarray(list(reader))
    peak_nonzero_id = np.nonzero(count_mat.sum(axis=1))[0]
    random.seed(2022)
    random_cellbarcode_list = cellbarcode_generator(n_cell, size=16)
    with open(OUTPUT_cells_barcode_file, 'w') as f:
        for item in random_cellbarcode_list:
            f.write(item + "\n")
    cellbarcode_list_withclusters = np.vstack((random_cellbarcode_list, count_mat_cluster)).transpose()
    with open(OUTPUT_cells_barcode_file + ".withSynthCluster", 'w') as f:
        for item in cellbarcode_list_withclusters:
            f.write("\t".join(item) + "\n")
    # Create read 1 and read 2 files
    with open("%s/%s.read1.bed" % (outdirectory, read_bedfile_prename), 'w') as f_1:
        pass
    with open("%s/%s.read2.bed" % (outdirectory, read_bedfile_prename), 'w') as f_2:
        pass
    # w/ Target Peak
    print("[scReadSim] Generating Synthetic Reads for Feature Set: %s" % (target_peak_assignment_file))
    for relative_peak_ind in tqdm(range(len(peak_nonzero_id))):
        peak_ind = peak_nonzero_id[relative_peak_ind]
        rec = open_peak[peak_ind]
        rec_name = '_'.join(rec)
        true_peak_concat = rec[3] + ":" + str(rec[4]) + "-" + str(rec[5])
        target_peak_concat = rec[0] + ":" + str(rec[1]) + "-" + str(rec[2])
        if int(rec[2]) - int(rec[1]) == 0:
            print("Peak %s has identical start and end position. Skip.")
            continue
        shift_number = int(rec[1]) - int(rec[4])
        reads = samfile.fetch(rec[3], int(rec[4]), int(rec[5])) # Extract reads from true peaks
        # tic = time.time()
        # Extract read information
        reads_str = []
        for read in reads:
            if read.is_reverse==1:
                strand = -1
            else:
                strand = 1
            if read.is_read1==1:
                read_order = 1
            else:
                read_order = 2
            start = read.reference_start
            mate_start = read.next_reference_start
            read_len_cur = read.query_alignment_length
            read_info = [start, mate_start, read_len_cur, read_order, strand]
            reads_str.append(read_info)
        # Sample npair_read_synthetic read 1 from reads and reserve fragment length 
        if len(reads_str) > 0: # If no real reads exist in the peak, skip
            count_vec = count_mat[peak_ind,:] # Synthetic umi count
            count_frag_vec = np.ceil(count_vec/2).astype(int)
            npair_read_synthetic = np.sum(count_frag_vec).astype(int) # nrow(reads_cur) should equal to nfrag_cur
            # npair_read_synthetic = np.ceil(np.sum(count_vec)/2).astype(int) # total number of synthetic reads
            read_sampled_unsplit = np.array(reads_str)[np.random.choice(len(reads_str), size=npair_read_synthetic, replace=True),:]
            # Sample starting position if random noise mode is on, or use real read starting position
            if random_noise_mode == True:
                read_synthetic_start = np.random.randint(int(rec[1]), int(rec[2]), size=npair_read_synthetic)
            else:
                read_synthetic_start = read_sampled_unsplit[:,0].astype(int) + shift_number
            # Generate Read Name
            nonempty_cell_ind = np.where(count_frag_vec != 0)[0]
            target_peak_concat = rec[0] + ":" + str(rec[1]) + "-" + str(rec[2])
            read_name_list = [random_cellbarcode_list[nonempty_cell_ind[ind]] + "CellNo" + str(nonempty_cell_ind[ind] + 1) + ":" + str(target_peak_concat) + "#" + str(count).zfill(4) for ind in range(len(nonempty_cell_ind)) for count in range(count_frag_vec[nonempty_cell_ind[ind]])]
            # Create dataframe for unspiltted sampled reads
            reads_cur = pd.DataFrame({
                'chr': rec[0],
                'r_start': read_synthetic_start,
                'mate_start': read_sampled_unsplit[:,1].astype(int) + read_synthetic_start - read_sampled_unsplit[:,0].astype(int),
                'read_name': read_name_list,
                'length': read_sampled_unsplit[:,2],
                'read_order': read_sampled_unsplit[:,3].astype(int),
                'strand': read_sampled_unsplit[:,4].astype(int),
                'mate_strand': -read_sampled_unsplit[:,4].astype(int)
                })
            contain_read_indicator = read_sampled_unsplit[:,0] == read_sampled_unsplit[:,1]
            reads_cur['read_length'] = read_len
            reads_cur['read_length'][contain_read_indicator] = abs(reads_cur['length'].astype(int)[contain_read_indicator])
            # Add jitter size to read positions
            jitter_value_vec = np.random.randint(-jitter_size,jitter_size,size=npair_read_synthetic).astype(int)  # nrow(reads_cur) should equal to nfrag_cur
            reads_cur['r_start_shifted'] = reads_cur['r_start'].astype(int)  + jitter_value_vec
            reads_cur['mate_start_shifted'] = reads_cur['mate_start'].astype(int)  + jitter_value_vec
            reads_cur['r_end_shifted'] = reads_cur['r_start'].astype(int) + reads_cur['read_length'].astype(int) + jitter_value_vec
            reads_cur['mate_end_shifted'] = reads_cur['mate_start'].astype(int) + reads_cur['read_length'].astype(int) + jitter_value_vec
            # Split read 1 and read 2
            read_1_df = pd.concat([reads_cur.loc[reads_cur['read_order'] == 1, ['chr','r_start_shifted', 'r_end_shifted', 'read_length', 'strand']].rename(columns={'r_start_shifted':'r1_start_shifted', 'r_end_shifted':'r1_end_shifted'}), reads_cur.loc[reads_cur['read_order'] == 2, ['chr','mate_start_shifted', 'mate_end_shifted', 'read_length', 'mate_strand']].rename(columns={'mate_start_shifted':'r1_start_shifted', 'mate_end_shifted':'r1_end_shifted', 'mate_strand': 'strand'})], ignore_index=True)
            read_2_df = pd.concat([reads_cur.loc[reads_cur['read_order'] == 1, ['chr','mate_start_shifted', 'mate_end_shifted', 'read_length', 'mate_strand']].rename(columns={'mate_start_shifted':'r2_start_shifted', 'mate_end_shifted':'r2_end_shifted', 'mate_strand': 'strand'}), reads_cur.loc[reads_cur['read_order'] == 2, ['chr','r_start_shifted', 'r_end_shifted', 'read_length', 'strand']].rename(columns={'r_start_shifted':'r2_start_shifted', 'r_end_shifted':'r2_end_shifted'}), ], ignore_index=True)
            read_1_df['read_name'] = read_name_list
            read_2_df['read_name'] = read_name_list
            read_1_df['strand'] = ['+' if x == 1  else '-' for x in read_1_df['strand']]
            read_2_df['strand'] = ['+' if x == 1  else '-' for x in read_2_df['strand']]
            read_1_df_order = read_1_df[['chr','r1_start_shifted', 'r1_end_shifted', 'read_name', 'read_length', 'strand']]
            read_2_df_order = read_2_df[['chr','r2_start_shifted', 'r2_end_shifted', 'read_name', 'read_length', 'strand']]
            if read_2_df_order.shape[0] != read_2_df_order.shape[0]:
                print("Peak %s read 1 and read 2 not identical!", relative_peak_ind)
            if np.sum(np.array(read_1_df_order[['r1_start_shifted']] < 0)) + np.sum(np.array(read_2_df_order[['r2_start_shifted']] < 0)) > 0:
                print("[Warning] Synthetic read pair for Peak %s %s has read 1 or read 2 start position negative: synthetic read pair removed!" % (relative_peak_ind, rec_name))
                ind_preserve = np.array(read_1_df_order[['r1_start_shifted']] >= 0) * np.array(read_2_df_order[['r2_start_shifted']] >= 0) # Remove rows with read 1 or read 2's start position negative
                read_1_df_order_removeNegRead = read_1_df_order.loc[ind_preserve]
                read_2_df_order_removeNegRead = read_2_df_order.loc[ind_preserve]
            else:
                read_1_df_order_removeNegRead = read_1_df_order
                read_2_df_order_removeNegRead = read_2_df_order
            read_1_df_order_removeNegRead.to_csv("%s/%s.read1.bed" % (outdirectory, read_bedfile_prename), header=None, index=None, sep='\t', mode='a')
            read_2_df_order_removeNegRead.to_csv("%s/%s.read2.bed" % (outdirectory, read_bedfile_prename), header=None, index=None, sep='\t', mode='a')
    print("\n[scReadSim] Created:")
    print("[scReadSim] Read 1 bed file: %s/%s.read1.bed" % (outdirectory, read_bedfile_prename))
    print("[scReadSim] Read 2 bed file: %s/%s.read2.bed" % (outdirectory, read_bedfile_prename))
    print("[scReadSim] Done.")


def scATAC_CombineBED(outdirectory, BED_filename_pre, BED_COMPLE_filename_pre, BED_filename_combined_pre, GrayAreaModeling=True):
    """Combine the bed files of foreground and background feature sets into one bed file.

    Parameters
    ----------
    outdirectory: `str`
        Directory of `BED_filename_pre`.txt and `BED_COMPLE_filename_pre`.txt.
    BED_filename_pre: `str`
        File prename of foreground synthetic reads bed file.
    BED_COMPLE_filename_pre: 'str'
        File prename of background synthetic reads bed file.
    BED_filename_combined_pre: 'str'
        Specify the combined syntehtic reads bed file prename. The combined bed file will be output to `outdirectory`.
    GrayAreaModeling: `bool` (default: 'True')
        Specify whether to combine gray area's reads.
   """
    if GrayAreaModeling:
        print("[scReadSim] Combining Synthetic Read 1 Bed Files from Peaks, NonPeaks and GrayAreas.")
        combine_read1_cmd = "cat %s/%s.read1.bed %s/%s.read1.bed %s/%s.GrayArea.read1.bed > %s/%s.read1.bed" % (outdirectory, BED_filename_pre, outdirectory, BED_COMPLE_filename_pre, outdirectory, BED_COMPLE_filename_pre, outdirectory, BED_filename_combined_pre)
        output, error = subprocess.Popen(combine_read1_cmd, shell=True, executable="/bin/bash", stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()
        if error:
            print('[ERROR] Fail to create combine synthetic read1 bed files:\n', error.decode())
        print("[scReadSim] Combining Synthetic Read 2 Bed Files from Peaks, NonPeaks and GrayAreas.")
        combine_read2_cmd = "cat %s/%s.read2.bed %s/%s.read2.bed %s/%s.GrayArea.read2.bed > %s/%s.read2.bed" % (outdirectory, BED_filename_pre, outdirectory, BED_COMPLE_filename_pre, outdirectory, BED_COMPLE_filename_pre, outdirectory, BED_filename_combined_pre)
        output, error = subprocess.Popen(combine_read2_cmd, shell=True, executable="/bin/bash", stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()
        if error:
            print('[ERROR] Fail to create combine synthetic read2 bed files:\n', error.decode())
            # sys.exit('[ERROR] Fail to create combine synthetic read2 bed files:\n', error.decode())
    else:
        print("[scReadSim] Combining Synthetic Read 1 Bed Files from Peaks, NonPeaks.")
        combine_read1_cmd = "cat %s/%s.read1.bed %s/%s.read1.bed > %s/%s.read1.bed" % (outdirectory, BED_filename_pre, outdirectory, BED_COMPLE_filename_pre, outdirectory, BED_filename_combined_pre)
        output, error = subprocess.Popen(combine_read1_cmd, shell=True, executable="/bin/bash", stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()
        if error:
            print('[ERROR] Fail to create combine synthetic read1 bed files:\n', error.decode())
        print("[scReadSim] Combining Synthetic Read 2 Bed Files from Peaks, NonPeaks.")
        combine_read2_cmd = "cat %s/%s.read2.bed %s/%s.read2.bed > %s/%s.read2.bed" % (outdirectory, BED_filename_pre, outdirectory, BED_COMPLE_filename_pre, outdirectory, BED_filename_combined_pre)
        output, error = subprocess.Popen(combine_read2_cmd, shell=True, executable="/bin/bash", stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()
        if error:
            print('[ERROR] Fail to create combine synthetic read2 bed files:\n', error.decode())
            # sys.exit('[ERROR] Fail to create combine synthetic read2 bed files:\n', error.decode())        
    print("\n[scReadSim] Created:")
    print("[scReadSim] Combined Read 1 Bed File: %s/%s.read1.bed" % (outdirectory, BED_filename_combined_pre))
    print("[scReadSim] Combined Read 2 Bed File: %s/%s.read2.bed" % (outdirectory, BED_filename_combined_pre))
    print("[scReadSim] Done.")


def scATAC_BED2FASTQ(bedtools_directory, seqtk_directory, referenceGenome_file, outdirectory, BED_filename_combined, synthetic_fastq_prename):
    """Convert Synthetic reads from BED to FASTQ. 

    Parameters
    ----------
    bedtools_directory: `str`
        Directory of software bedtools.
    seqtk_directory: `str`
        Directory of software seqtk.
    referenceGenome_file: `str`
        Directory of the reference genome FASTA file that the synthteic reads should align.
    outdirectory: `str`
        Output directory of the synthteic bed file and its corresponding cell barcodes file.
    BED_filename_combined: `str`
        Specify the base name of output bed file of function 'scATAC_CombineBED'.
    synthetic_fastq_prename: `str`
        Specify the base name of the output FASTQ files.
    """
	# Create FASTA
    print('[scReadSim] Generating Synthetic Read FASTA files...')
    fasta_read1_cmd = "%s/bedtools getfasta -s -fi %s -bed %s/%s.read1.bed -fo %s/%s.read1.bed2fa.strand.fa -nameOnly" % (bedtools_directory, referenceGenome_file, outdirectory, BED_filename_combined, outdirectory, synthetic_fastq_prename)
    output, error = subprocess.Popen(fasta_read1_cmd, shell=True, executable="/bin/bash", stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()
    if error:
        print(error.decode())
    fasta_read2_cmd = "%s/bedtools getfasta -s -fi %s -bed %s/%s.read2.bed -fo %s/%s.read2.bed2fa.strand.fa -nameOnly" % (bedtools_directory, referenceGenome_file, outdirectory, BED_filename_combined, outdirectory, synthetic_fastq_prename)
    output, error = subprocess.Popen(fasta_read2_cmd, shell=True, executable="/bin/bash", stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()
    if error:
        print(error.decode())
 	# remove (-) or (+)
    org_fasta_read1_cmd = "sed '/^>/s/.\{3\}$//' %s/%s.read1.bed2fa.strand.fa > %s/%s.read1.bed2fa.fa" % (outdirectory, synthetic_fastq_prename, outdirectory, synthetic_fastq_prename)
    output, error = subprocess.Popen(org_fasta_read1_cmd, shell=True, executable="/bin/bash", stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()
    if error:
        print('[ERROR] Fail to remove strand infomormation from synthetic read1 fasta file:', error.decode())
    org_fasta_read2_cmd = "sed '/^>/s/.\{3\}$//' %s/%s.read2.bed2fa.strand.fa > %s/%s.read2.bed2fa.fa" % (outdirectory, synthetic_fastq_prename, outdirectory, synthetic_fastq_prename)
    output, error = subprocess.Popen(org_fasta_read2_cmd, shell=True, executable="/bin/bash", stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()
    if error:
        print('[ERROR] Fail to remove strand infomormation from synthetic read2 fasta file:', error.decode())
	# FASTA to FASTQ
    print('[scReadSim] Generating Synthetic Read FASTQ files...')
    fastq_read1_cmd = "%s/seqtk seq -F 'F' %s/%s.read1.bed2fa.fa > %s/%s.read1.bed2fa.fq" % (seqtk_directory, outdirectory, synthetic_fastq_prename, outdirectory, synthetic_fastq_prename)
    output, error = subprocess.Popen(fastq_read1_cmd, shell=True, executable="/bin/bash", stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()
    if error:
        print('[ERROR] Fail to convert read1 synthetic fasta file to fastq file:', error.decode())
    fastq_read2_cmd = "%s/seqtk seq -F 'F' %s/%s.read2.bed2fa.fa > %s/%s.read2.bed2fa.fq" % (seqtk_directory, outdirectory, synthetic_fastq_prename, outdirectory, synthetic_fastq_prename)
    output, error = subprocess.Popen(fastq_read2_cmd, shell=True, executable="/bin/bash", stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()
    if error:
        print('[ERROR] Fail to convert read2 synthetic fasta file to fastq file:', error.decode())
    print('[scReadSim] Sorting FASTQ files...')
    sort_fastq_read1_cmd = "cat %s/%s.read1.bed2fa.fq | paste - - - - | sort -k1,1 -S 3G | tr '\t' '\n' > %s/%s.read1.bed2fa.sorted.fq" % (outdirectory, synthetic_fastq_prename, outdirectory, synthetic_fastq_prename)
    output, error = subprocess.Popen(sort_fastq_read1_cmd, shell=True, executable="/bin/bash", stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()
    if error:
        print('[ERROR] Fail to sort read1 synthetic fastq file:', error.decode())
    sort_fastq_read2_cmd = "cat %s/%s.read2.bed2fa.fq | paste - - - - | sort -k1,1 -S 3G | tr '\t' '\n' > %s/%s.read2.bed2fa.sorted.fq" % (outdirectory, synthetic_fastq_prename, outdirectory, synthetic_fastq_prename)
    output, error = subprocess.Popen(sort_fastq_read2_cmd, shell=True, executable="/bin/bash", stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()
    if error:
        print('[ERROR] Fail to sort read2 synthetic fastq file:', error.decode())
    print("\n[scReadSim] Created:")
    print("[scReadSim] Read 1 FASTQ File: %s/%s.read1.bed2fa.sorted.fq" % (outdirectory, synthetic_fastq_prename))
    print("[scReadSim] Read 2 FASTQ File: %s/%s.read2.bed2fa.sorted.fq" % (outdirectory, synthetic_fastq_prename))
    print("[scReadSim] Done.")


def AlignSyntheticBam_Pair(bowtie2_directory, samtools_directory, outdirectory, referenceGenome_name, referenceGenome_dir, synthetic_fastq_prename, output_BAM_pre):
    """Convert Synthetic reads from FASTQ to BAM. 

    Parameters
    ----------
    bowtie2_directory: `str`
        Path to software bowtie2.
    samtools_directory: `str`
        Path to software samtools.
    outdirectory: `str`
        Specify the output directory of the synthteic BAM file.
    referenceGenome_name: `str`
        Base name of the eference genome FASTA file. For example, you should input "chr1" for file "chr1.fa".
    referenceGenome_dir: `str`
        Path to the reference genome FASTA file.
    synthetic_fastq_prename: `str`
        Base name of the synthetic FASTQ files output by function `scATAC_BED2FASTQ`.
    output_BAM_pre: `str`
        Specify the base name of the output BAM file.
    """
    print('[scReadSim] Aligning FASTQ files onto Reference Genome Files with Bowtie2...')
    alignment_cmd = "%s/bowtie2 --minins 0 --maxins 1200 -x %s/%s -1 %s/%s.read1.bed2fa.sorted.fq -2 %s/%s.read2.bed2fa.sorted.fq | %s/samtools view -bS - > %s/%s.synthetic.noCB.bam" % (bowtie2_directory, referenceGenome_dir, referenceGenome_name,  outdirectory, synthetic_fastq_prename, outdirectory, synthetic_fastq_prename, samtools_directory, outdirectory, output_BAM_pre)
    output, error = subprocess.Popen(alignment_cmd, shell=True, executable="/bin/bash", stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()
    print('[Bowtie2] Aligning:\n', error.decode())
    print('[scReadSim] Alignment Done.')
    print('[scReadSim] Generating Cell Barcode Tag...')
    addBC2BAM_header_cmd = "%s/samtools view %s/%s.synthetic.noCB.bam -H > %s/%s.synthetic.noCB.header.sam" % (samtools_directory, outdirectory, output_BAM_pre, outdirectory, output_BAM_pre)
    output, error = subprocess.Popen(addBC2BAM_header_cmd, shell=True, executable="/bin/bash", stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()
    addBC2BAM_cmd = "cat <( cat %s/%s.synthetic.noCB.header.sam ) <( paste <(%s/samtools view %s/%s.synthetic.noCB.bam ) <(%s/samtools view %s/%s.synthetic.noCB.bam | cut -f1 | cut -d':' -f1 | sed -e 's/^/CB:Z:/')) | %s/samtools view -bS - > %s/%s.synthetic.bam" % (outdirectory, output_BAM_pre, samtools_directory, outdirectory, output_BAM_pre, samtools_directory, outdirectory, output_BAM_pre, samtools_directory, outdirectory, output_BAM_pre)
    output, error = subprocess.Popen(addBC2BAM_cmd, shell=True, executable="/bin/bash", stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()
    if error:
        print('[ERROR] Fail to add BC tag to synthetic BAM file:', error.decode())
    print('[scReadSim] Sorting and Indexing BAM file...')
    sortBAMcmd = "%s/samtools sort %s/%s.synthetic.bam > %s/%s.synthetic.sorted.bam" % (samtools_directory, outdirectory, output_BAM_pre, outdirectory, output_BAM_pre)
    output, error = subprocess.Popen(sortBAMcmd, shell=True, executable="/bin/bash", stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()
    if error:
        print('[ERROR] Fail to sort synthetic BAM file:', error.decode())
    indexBAMcmd = "%s/samtools index %s/%s.synthetic.sorted.bam" % (samtools_directory, outdirectory, output_BAM_pre)
    output, error = subprocess.Popen(indexBAMcmd, shell=True, executable="/bin/bash", stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()
    if error:
        print('[ERROR] Fail to index synthetic BAM file:', error.decode())
    print("\n[scReadSim] Created:")
    print("[scReadSim] Synthetic Read BAM File: %s/%s.synthetic.sorted.bam" % (outdirectory, output_BAM_pre))
    print("[scReadSim] Done.")


def ErrorBase(base, prop, base_call_ref):
	"""Sample random errors. 

	"""
	err_base_call_id = np.random.choice(a=[0, 1, 2], size=1, p=prop)[0]      
	err_base_call = base_call_ref[base][err_base_call_id]
	return err_base_call


def ErroneousRead(real_error_rate_read, read_df, output_fq_file):
	"""Generate random errors according to input real data error rates. 

	"""
	n_read = int(np.shape(read_df)[0]/4)
	## Prepare Error rate
	real_error_rate_read_A = real_error_rate_read[['a_to_c_error_rate', 'a_to_g_error_rate', 'a_to_t_error_rate']].to_numpy() 
	real_error_rate_read_A_prop = real_error_rate_read_A/real_error_rate_read_A.sum(axis=1,keepdims=1)
	real_error_rate_read_A_prop[np.isnan(real_error_rate_read_A_prop).any(axis=1),:] = 1/3
	real_error_rate_read_C = real_error_rate_read[['c_to_a_error_rate', 'c_to_g_error_rate', 'c_to_t_error_rate']].to_numpy() 
	real_error_rate_read_C_prop = real_error_rate_read_C/real_error_rate_read_C.sum(axis=1,keepdims=1)
	real_error_rate_read_C_prop[np.isnan(real_error_rate_read_C_prop).any(axis=1),:] = 1/3
	real_error_rate_read_G = real_error_rate_read[['g_to_a_error_rate', 'g_to_c_error_rate', 'g_to_t_error_rate']].to_numpy() 
	real_error_rate_read_G_prop = real_error_rate_read_G/real_error_rate_read_G.sum(axis=1,keepdims=1)
	real_error_rate_read_G_prop[np.isnan(real_error_rate_read_G_prop).any(axis=1),:] = 1/3
	real_error_rate_read_T = real_error_rate_read[['t_to_a_error_rate', 't_to_c_error_rate', 't_to_g_error_rate']].to_numpy() 
	real_error_rate_read_T_prop = real_error_rate_read_T/real_error_rate_read_T.sum(axis=1,keepdims=1)
	real_error_rate_read_T_prop[np.isnan(real_error_rate_read_T_prop).any(axis=1),:] = 1/3
	# Base decision matrix
	real_error_rate_read_prop_dict = {'A': real_error_rate_read_A_prop, 'C': real_error_rate_read_C_prop, 'G': real_error_rate_read_G_prop, 'T': real_error_rate_read_T_prop}
	# Error decision vector
	real_error_rate_read_perbase = real_error_rate_read['error_rate'].to_numpy()
	## Decide whether error occurs for each read
	read_length = real_error_rate_read.shape[0]
	error_read_perbase_indicator = np.zeros((n_read, read_length), dtype=int)
	random.seed(1)
	for base_id in range(read_length):
		error_read_perbase_indicator[:,base_id] = np.random.binomial(n=1, p=real_error_rate_read_perbase[base_id], size=n_read)
	erroneous_read_id = np.where(np.sum(error_read_perbase_indicator, axis=1) > 0)[0]
	## For erroneous reads, generate erroneous base based on the probability matrix
	base_call_ref = {'A': ['C', 'G', 'T'], 'C': ['A', 'G', 'T'], 'G': ['A', 'C', 'T'], 'T': ['A', 'C', 'G']}
	random.seed(2021)
	read_df_witherror = read_df
	for read_id_tqdm in tqdm(range(len(erroneous_read_id))):
		read_id = erroneous_read_id[read_id_tqdm]
		read_cur = read_df[(read_id*4) : (read_id*4 + 4)]
		bases = list(read_cur[1][0].upper())
		Qscores = list(read_cur[3][0])
		for errorneous_base_id in np.where(error_read_perbase_indicator[read_id,:] > 0)[0]:
			if errorneous_base_id < len(bases):
				base_cur = bases[errorneous_base_id]
				if base_cur in real_error_rate_read_prop_dict:
					prop = real_error_rate_read_prop_dict[base_cur][errorneous_base_id]
					# Decide error base
					err_base_call = ErrorBase(base_cur, prop, base_call_ref)
					bases[errorneous_base_id] = err_base_call
					# Decide Q score
					# Use 9 (Phred score 24) for erroneous base
					Qscores[errorneous_base_id] = '9'
		read_df_witherror[read_id*4+1] = ''.join(bases)
		read_df_witherror[read_id*4+3] = ''.join(Qscores)
	## Write out
	np.savetxt(output_fq_file, read_df_witherror, fmt='%s')


def SubstiError_Pair(real_error_rate_file, outdirectory, synthetic_fastq_prename):
	"""Generate random errors for paired-end sequencing reads according to input real data error rates. 

	Parameters
	----------
	real_error_rate_file: `str`
		Path to software fgbio jar script.
	outdirectory: `str`
		Specify the output directory of the synthteic FASTQ file with random errors.
	synthetic_fastq_prename: `str`
		Specify the base name of the synthetic erroneous reads' FASTQ files.
	"""
	# Read in real error rates
	real_error_rate_dir = real_error_rate_file
	real_error_rate = pd.read_csv(real_error_rate_dir, header=0, delimiter="\t")
	real_error_rate_read1 = real_error_rate[real_error_rate['read_number'] == 1]
	real_error_rate_read2 = real_error_rate[real_error_rate['read_number'] == 2]
	# Read in perfect reads
	read1_fq = outdirectory  + "/" + synthetic_fastq_prename + ".read1.bed2fa.fq"
	read2_fq = outdirectory  + "/" + synthetic_fastq_prename + ".read2.bed2fa.fq"
	read1_df = pd.read_csv(read1_fq, header=None).to_numpy()
	read2_df = pd.read_csv(read2_fq, header=None).to_numpy()
	# Generate random error according to Real data
	ErroneousRead(real_error_rate_read1, read1_df, outdirectory + "/" + synthetic_fastq_prename + ".ErrorIncluded.read1.bed2fa.fq") 
	ErroneousRead(real_error_rate_read2, read2_df, outdirectory + "/" + synthetic_fastq_prename + ".ErrorIncluded.read2.bed2fa.fq") 


def scATAC_ErrorBase(fgbio_jarfile, INPUT_bamfile, referenceGenome_file, outdirectory, synthetic_fastq_prename):
	"""Introduce random substitution errors into synthetic reads according to real data error rates.

	Parameters
	----------
	fgbio_jarfile: `str`
		Path to software fgbio jar script.
	INPUT_bamfile: `str`
		Input BAM file for anlaysis.
	referenceGenome_file: 'str'
		Reference genome FASTA file that the synthteic reads should align.
	outdirectory: `str`
		Specify the output directory of the synthteic FASTQ file with random errors.
	synthetic_fastq_prename: `str`
		Base name of the synthetic FASTQ files output by function `scATAC_BED2FASTQ`.
	"""
	print('[scReadSim] Substitution Error Calculating...')
	combine_read1_cmd = "java -jar %s ErrorRateByReadPosition -i %s -r %s -o %s/Real --collapse false" % (fgbio_jarfile, INPUT_bamfile, referenceGenome_file, outdirectory)
	output, error = subprocess.Popen(combine_read1_cmd, shell=True, executable="/bin/bash", stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()
	if error:
		print('[Messages] Running fgbio on real bam file:\n', error.decode())
	# Generate Errors into fastq files
	print('[scReadSim] Generting Synthetic Read FASTQ Files with Substitution Errors...')
	real_error_rate_file = outdirectory + "/" + "Real.error_rate_by_read_position.txt"
	SubstiError_Pair(real_error_rate_file, outdirectory, synthetic_fastq_prename)
	# Combine FASTQs
	print('[scReadSim] Sorting FASTQ files...')
	sort_fastq_read1_cmd = "cat %s/%s.ErrorIncluded.read1.bed2fa.fq | paste - - - - | sort -k1,1 -S 3G | tr '\t' '\n' > %s/%s.ErrorIncluded.read1.bed2fa.sorted.fq" % (outdirectory, synthetic_fastq_prename, outdirectory, synthetic_fastq_prename)
	output, error = subprocess.Popen(sort_fastq_read1_cmd, shell=True, executable="/bin/bash", stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()
	if error:
		print('[ERROR] Fail to sort read1 synthetic fastq file:', error.decode())
	sort_fastq_read2_cmd = "cat %s/%s.ErrorIncluded.read2.bed2fa.fq | paste - - - - | sort -k1,1 -S 3G | tr '\t' '\n' > %s/%s.ErrorIncluded.read2.bed2fa.sorted.fq" % (outdirectory, synthetic_fastq_prename, outdirectory, synthetic_fastq_prename)
	output, error = subprocess.Popen(sort_fastq_read2_cmd, shell=True, executable="/bin/bash", stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()
	if error:
			print('[ERROR] Fail to sort read2 synthetic fastq file:', error.decode())
	print("\n[scReadSim] Created:")
	print("[scReadSim] Read 1 FASTQ File with Substitution Error: %s/%s.ErrorIncluded.read1.bed2fa.sorted.fq" % (outdirectory, synthetic_fastq_prename))
	print("[scReadSim] Read 2 FASTQ File with Substitution Error: %s/%s.ErrorIncluded.read2.bed2fa.sorted.fq" % (outdirectory, synthetic_fastq_prename))
	print("[scReadSim] Done.")







