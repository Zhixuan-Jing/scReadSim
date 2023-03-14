import sys, os
import scReadSim.Utility as Utility
import scReadSim.GenerateSyntheticCount as GenerateSyntheticCount
import scReadSim.scATAC_GenerateBAM as scATAC_GenerateBAM
import pkg_resources

outdirectory = "./results"
INPUT_cells_barcode_file = pkg_resources.resource_filename("scReadSim", 'scReadSim/data/barcodes.tsv')
filename = "10X_ATAC_chr1_4194444_4399104"
INPUT_bamfile = pkg_resources.resource_filename("scReadSim", 'scReadSim/data/%s.bam' % filename)
INPUT_genome_size_file = pkg_resources.resource_filename("scReadSim", 'scReadSim/data/mm10.chrom.sizes')


Utility.scATAC_CreateFeatureSets(INPUT_bamfile, samtools_directory, bedtools_directory, outdirectory, INPUT_genome_size_file, macs3_directory, INPUT_peakfile=None, INPUT_nonpeakfile=None)

# Specify the path to bed files generated by Utility.scATAC_CreateFeatureSets
peak_bedfile = outdirectory + "/" + "scReadSim.MACS3.peak.bed"
nonpeak_bedfile = outdirectory + "/" + "scReadSim.MACS3.nonpeak.bed"
# Specify the output count matrices' prenames
count_mat_peak_filename = "%s.peak.countmatrix" % filename
count_mat_nonpeak_filename = "%s.nonpeak.countmatrix" % filename

# Construct count matrix for peaks
Utility.scATAC_bam2countmat_paral(cells_barcode_file=INPUT_cells_barcode_file, bed_file=peak_bedfile, INPUT_bamfile=INPUT_bamfile, outdirectory=outdirectory, count_mat_filename=count_mat_peak_filename, n_cores=1)
# Construct count matrix for non-peaks
Utility.scATAC_bam2countmat_paral(cells_barcode_file=INPUT_cells_barcode_file, bed_file=nonpeak_bedfile, INPUT_bamfile=INPUT_bamfile, outdirectory=outdirectory, count_mat_filename=count_mat_nonpeak_filename, n_cores=1)

# Generate synthetic count matrix for peak-by-cell count matrix
GenerateSyntheticCount.scATAC_GenerateSyntheticCount(count_mat_filename=count_mat_peak_filename, directory=outdirectory, outdirectory=outdirectory)
# Generate synthetic count matrix for nonpeak-by-cell count matrix
GenerateSyntheticCount.scATAC_GenerateSyntheticCount(count_mat_filename=count_mat_nonpeak_filename, directory=outdirectory, outdirectory=outdirectory)

# Specify the names of synthetic count matrices (generated by GenerateSyntheticCount.scATAC_GenerateSyntheticCount)
synthetic_countmat_peak_file = count_mat_peak_filename + ".scDesign2Simulated.txt"
synthetic_countmat_nonpeak_file = count_mat_nonpeak_filename + ".scDesign2Simulated.txt"
# Specify the base name of bed files containing synthetic reads
OUTPUT_cells_barcode_file = "synthetic_cell_barcode.txt"
peak_read_bedfile_prename = "%s.syntheticBAM.peak" % filename
nonpeak_read_bedfile_prename = "%s.syntheticBAM.nonpeak" % filename
BED_filename_combined_pre = "%s.syntheticBAM.combined" % filename
synthetic_cell_label_file = count_mat_peak_filename + ".scDesign2Simulated.CellTypeLabel.txt"

# Create synthetic read bed file for peaks
scATAC_GenerateBAM.scATAC_GenerateBAMCoord(bed_file=peak_bedfile, count_mat_file=outdirectory + "/" + synthetic_countmat_peak_file, synthetic_cell_label_file=synthetic_cell_label_file, read_bedfile_prename=peak_read_bedfile_prename, INPUT_bamfile=INPUT_bamfile, outdirectory=outdirectory, OUTPUT_cells_barcode_file=OUTPUT_cells_barcode_file, jitter_size=5, read_len=50)

# Create synthetic read bed file for non-peaks
scATAC_GenerateBAM.scATAC_GenerateBAMCoord(bed_file=nonpeak_bedfile, count_mat_file=outdirectory + "/" + synthetic_countmat_nonpeak_file, synthetic_cell_label_file=synthetic_cell_label_file, read_bedfile_prename=nonpeak_read_bedfile_prename, INPUT_bamfile=INPUT_bamfile, outdirectory=outdirectory, OUTPUT_cells_barcode_file=OUTPUT_cells_barcode_file, jitter_size=5, read_len=50,  GrayAreaModeling=True)

# Combine bed files
scATAC_GenerateBAM.scATAC_CombineBED(outdirectory=outdirectory, peak_read_bedfile_prename=peak_read_bedfile_prename, nonpeak_read_bedfile_prename=nonpeak_read_bedfile_prename, BED_filename_combined_pre=BED_filename_combined_pre)

referenceGenome_name = "chr1"
referenceGenome_dir = "/home/users/example/refgenome_dir"
referenceGenome_file = "%s/%s.fa" % (referenceGenome_dir, referenceGenome_name)
synthetic_fastq_prename = BED_filename_combined_pre

# Convert combined bed file into FASTQ files
scATAC_GenerateBAM.scATAC_BED2FASTQ(bedtools_directory=bedtools_directory, seqtk_directory=seqtk_directory, referenceGenome_file=referenceGenome_file, outdirectory=outdirectory, BED_filename_combined=BED_filename_combined_pre, synthetic_fastq_prename=synthetic_fastq_prename)

