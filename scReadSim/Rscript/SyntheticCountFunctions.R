# Check if packages are installed
if (!require("BiocManager", quietly = TRUE))
    install.packages("BiocManager")
if (!require("Rsubread", quietly = TRUE))
    BiocManager::install("Rsubread")
if (!requireNamespace("ROGUE", quietly = TRUE)) {
  if (!requireNamespace("devtools", quietly = TRUE)) 
    install.packages("devtools")
devtools::install_github("PaulingLiu/ROGUE")
}
if (!requireNamespace("scDesign2", quietly = TRUE)) {
  if (!requireNamespace("devtools", quietly = TRUE)) 
    install.packages("devtools")
devtools::install_github("JSB-UCLA/scDesign2")
}

# Load packages
library(Matrix)
library(Rsubread)
library(pscl)
library(parallel)
library(MASS)
library(tidyverse)
library(ROGUE)
library(Seurat)

### Functions
fit_marginals_new <- function(x, marginal = c('auto_choose', 'zinb', 'nb', 'poisson'),
                          pval_cutoff = 0.05, epsilon = 1e-5,
                          jitter = TRUE, DT = TRUE){
  p <- nrow(x)
  n <- ncol(x)

  marginal <- match.arg(marginal)
  if(marginal == 'auto_choose'){
    params <- t(apply(x, 1, function(gene){
      m <- mean(gene)
      v <- var(gene)
      if(m >= v){
        mle_Poisson <- glm(gene ~ 1, family = poisson)
        tryCatch({
          mle_ZIP <- zeroinfl(gene ~ 1|1, dist = 'poisson')
          chisq_val <- 2 * (logLik(mle_ZIP) - logLik(mle_Poisson))
          pvalue <- as.numeric(1 - pchisq(chisq_val, 1))
          if(pvalue < pval_cutoff)
            c(plogis(mle_ZIP$coefficients$zero), Inf, exp(mle_ZIP$coefficients$count))
          else
            c(0.0, Inf, m)
        },
        error = function(cond){
          c(0.0, Inf, m)})
      }else{
        mle_NB <- glm.nb(gene ~ 1)
        if(min(gene) > 0)
          c(0.0, mle_NB$theta, exp(mle_NB$coefficients))
        else
          tryCatch({
            mle_ZINB <- zeroinfl(gene ~ 1|1, dist = 'negbin')
            chisq_val <- 2 * (logLik(mle_ZINB) - logLik(mle_NB))
            pvalue <- as.numeric(1 - pchisq(chisq_val, 1))
            if(pvalue < pval_cutoff)
              c(plogis(mle_ZINB$coefficients$zero), mle_ZINB$theta, exp(mle_ZINB$coefficients$count))
            else
              c(0.0, mle_NB$theta, exp(mle_NB$coefficients))
          },
          error = function(cond){
            c(0.0, mle_NB$theta, exp(mle_NB$coefficients))
          })
      }
    }))
  }else if(marginal == 'zinb'){
    params <- t(apply(x, 1, function(gene){
      m <- mean(gene)
      v <- var(gene)
      if(m >= v)
      {
        mle_Poisson <- glm(gene ~ 1, family = poisson)
        tryCatch({
          mle_ZIP <- zeroinfl(gene ~ 1|1, dist = 'poisson')
          chisq_val <- 2 * (logLik(mle_ZIP) - logLik(mle_Poisson))
          pvalue <- as.numeric(1 - pchisq(chisq_val, 1))
          if(pvalue < pval_cutoff)
            c(plogis(mle_ZIP$coefficients$zero), Inf, exp(mle_ZIP$coefficients$count))
          else
            c(0.0, Inf, m)
        },
        error = function(cond){
          c(0.0, Inf, m)})
      }
      else
      {
        if(min(gene) > 0)
        {
          mle_NB <- glm.nb(gene ~ 1)
          c(0.0, mle_NB$theta, exp(mle_NB$coefficients))
        }
        else
          tryCatch({
            mle_ZINB <- zeroinfl(gene ~ 1|1, dist = 'negbin')
            c(plogis(mle_ZINB$coefficients$zero), mle_ZINB$theta, exp(mle_ZINB$coefficients$count))
          },
          error = function(cond){
            mle_NB <- glm.nb(gene ~ 1)
            c(0.0, mle_NB$theta, exp(mle_NB$coefficients))
          })
      }
    }))
  }else if(marginal == 'nb'){
    params <- t(apply(x, 1, function(gene){
      m <- mean(gene)
      v <- var(gene)
      if(m >= v){
        c(0.0, Inf, m)
      }else{
        mle_NB <- glm.nb(gene ~ 1)
        c(0.0, mle_NB$theta, exp(mle_NB$coefficients))
      }
    }))
  }else if(marginal == 'poisson'){
    params <- t(apply(x, 1, function(gene){
      c(0.0, Inf, mean(gene))
    }))
  }

  if(DT){
    u <- t(sapply(1:p, function(iter){
      param <- params[iter, ]
      gene <- unlist(x[iter, ])
      prob0 <- param[1]
      u1 <- prob0 + (1 - prob0) * pnbinom(gene, size = param[2], mu = param[3])
      u2 <- (prob0 + (1 - prob0) * pnbinom(gene - 1, size = param[2], mu = param[3])) *
        as.integer(gene > 0)
      if(jitter)
        v <- runif(n)
      else
        v <- rep(0.5, n)
      r <- u1 * v + u2 * (1 - v)
      idx_adjust <- which(1-r < epsilon)
      r[idx_adjust] <- r[idx_adjust] - epsilon
      idx_adjust <- which(r < epsilon)
      r[idx_adjust] <- r[idx_adjust] + epsilon

      r
    }))
  }else{
    u <- NULL
  }

  return(list(params = params, u = u))
}

fit_Gaussian_copula_new <- function(x, marginal = c('auto_choose', 'zinb', 'nb', 'poisson'),
                                jitter = TRUE, zp_cutoff = 0.8,
                                min_nonzero_num = 2){
  marginal <- match.arg(marginal)
  n <- ncol(x)
  p <- nrow(x)

  gene_zero_prop <- apply(x, 1, function(y){
    sum(y < 1e-5) / n
  })

  gene_sel1 <- which(gene_zero_prop < zp_cutoff)
  gene_sel2 <- which(gene_zero_prop < 1.0 - min_nonzero_num/n &
                       gene_zero_prop >= zp_cutoff)
  gene_sel3 <- if (length(gene_sel1)+length(gene_sel2) == 0){
    1:p
  } else {
    (1:p)[-c(gene_sel1, gene_sel2)]
  }

  if(length(gene_sel1) > 0){
    marginal_result1 <- fit_marginals_new(x[gene_sel1, , drop = FALSE], marginal, jitter = jitter, DT = TRUE)
    quantile_normal <- qnorm(marginal_result1$u)
    cov_mat <- cor(t(quantile_normal))
  }else{
    cov_mat = NULL
    marginal_result1 = NULL
  }

  if(length(gene_sel2) > 0){
    marginal_result2 <- fit_marginals_new(x[gene_sel2, , drop = FALSE], marginal, DT = FALSE)
  }else{
    marginal_result2 = NULL
  }
  return(list(cov_mat = cov_mat, marginal_param1 = marginal_result1$params,
              marginal_param2 = marginal_result2$params,
              gene_sel1 = gene_sel1, gene_sel2 = gene_sel2, gene_sel3 = gene_sel3,
              zp_cutoff = zp_cutoff, min_nonzero_num = min_nonzero_num,
              sim_method = 'copula', n_cell = n, n_read = sum(x)))
}

fit_wo_copula_new <- function(x, marginal = c('auto_choose', 'zinb', 'nb', 'poisson'),
                          jitter = TRUE, min_nonzero_num = 2){
  marginal <- match.arg(marginal)
  n <- ncol(x)
  p <- nrow(x)

  gene_zero_prop <- apply(x, 1, function(y){
    sum(y < 1e-5) / n
  })

  gene_sel1 <- which(gene_zero_prop < 1.0 - min_nonzero_num/n)
  gene_sel2 <- which(gene_zero_prop < 1.0 - min_nonzero_num/n &
                       gene_zero_prop >= zp_cutoff)
  gene_sel3 <- if (length(gene_sel1)+length(gene_sel2) == 0){
    1:p
  } else {
    (1:p)[-c(gene_sel1, gene_sel2)]
  }

  if(length(gene_sel1) > 0){
    marginal_result1 <- fit_marginals_new(x[gene_sel1, ], marginal, jitter = jitter, DT = FALSE)
  }else{
    marginal_result1 = NULL
  }

  return(list(marginal_param1 = marginal_result1$params,
              gene_sel1 = gene_sel1, gene_sel2 = gene_sel2,
              min_nonzero_num = min_nonzero_num, sim_method = 'ind',
              n_cell = n, n_read = sum(x)))
}


fit_model_scDesign2_new <- function(data_mat, cell_type_sel, sim_method = c('copula', 'ind'),
                                marginal = c('auto_choose', 'zinb', 'nb', 'poisson'),
                                jitter = TRUE, zp_cutoff = 0.8,
                                min_nonzero_num = 2, ncores = 1){
  sim_method <- match.arg(sim_method)
  marginal <- match.arg(marginal)

  if(sum(abs(data_mat - round(data_mat))) > 1e-5){
    warning('The entries in the input matrix are not integers. Rounding is performed.')
    data_mat <- round(data_mat)
  }

  if(sim_method == 'copula'){
    param <- mclapply(1:length(cell_type_sel), function(iter){
      fit_Gaussian_copula_new(data_mat[, colnames(data_mat) == cell_type_sel[iter]], marginal,
                          jitter = jitter, zp_cutoff = zp_cutoff,
                          min_nonzero_num = min_nonzero_num)
    }, mc.cores = ncores)
  }else if(sim_method == 'ind'){
    param <- mclapply(1:length(cell_type_sel), function(iter){
      fit_wo_copula_new(data_mat[, colnames(data_mat) == cell_type_sel[iter]], marginal,
                    jitter = jitter,
                    min_nonzero_num = min_nonzero_num)
    }, mc.cores = ncores)
  }

  names(param) <- cell_type_sel
  return(param)
}

# function of getting a submatrix of selected cell types ----------------------------------
get_submat <- function(data_mat, cell_type_sel){
  if(is.null(colnames(data_mat))){
    data_mat
  }else{
    data_mat[, colnames(data_mat) %in% cell_type_sel]
  }
}
# function of using ROGUE scores to check cluster qualities -------------------------------
check_cluster_quality <- function(data_mat, cell_type_sel,
                                  platform = c("full-length", "UMI")){
  platform <- match.arg(platform)
  
  data_mat_sel <- get_submat(data_mat, cell_type_sel)
  
  expr <- data_mat_sel
  rogue.res <- rogue(expr, labels = colnames(expr),
                     samples = rep(1, ncol(expr)), platform = platform)
  unlist(rogue.res)
}

# function of using Seurat to cluster -----------------------------------------------------
get_cluster_seurat <- function(data_mat, n_cluster,
                               res = 0.5){
#   platform <- match.arg(platform)
  submat <- data_mat
  if(is.null(rownames(submat)))
    rownames(submat) <- 1:nrow(submat)
    count_seurat <- CreateSeuratObject(counts = submat, verbose = FALSE)
    ### normalization
    count_seurat <- NormalizeData(count_seurat,verbose = FALSE)
    ### select highly variable genes
    count_seurat <- FindVariableFeatures(count_seurat, selection.method = "vst", nfeatures = 4000,verbose = FALSE)
    ### scale the data
    count_seurat <- ScaleData(count_seurat,verbose = FALSE)
    ### PCA
    count_seurat <- RunPCA(count_seurat,
                            features = VariableFeatures(object = count_seurat),
                            verbose = F)
    ### clustering
    dims = 1:min(10, min(ncol(data_mat), nrow(data_mat))-1)
    count_seurat <- FindNeighbors(count_seurat, dims = dims)
  # If not specify target cluster number
    if (n_cluster == "default"){
        cat("No target cell cluster number detected.\n")        
        cat("Louvain clustering with default resolution 0.5...\n")        
        count_seurat <- FindClusters(count_seurat, resolution = res, verbose = FALSE)
        ### results
        cluster_predicted <- as.integer(Idents(count_seurat))
        colnames(submat) <- as.character(cluster_predicted)
        # rogue_scores <- check_cluster_quality(submat, unique(cluster_predicted), platform)
        cat(sprintf("%s cell clusters generated.\n", length(unique(cluster_predicted))))
    } else{
        n_cluster <- as.integer(n_cluster)
        cat(sprintf("Detected target cell cluster number %s\n", n_cluster))        
        cat("Generating target clusters with Louvain clustering through binary search...\n")        
        min_res <- 0
        max_res <- 3
        max_steps <- 20
        this_step <- 0
        while (this_step < max_steps) {
            cat('step', this_step,'\n')
            this_res <- min_res + ((max_res-min_res)/2)
            data_louvain <- Seurat::FindClusters(count_seurat, resolution = this_res, verbose = FALSE)
            this_clusters <- length(unique(Seurat::Idents(data_louvain)))
            if (this_clusters > n_cluster) {
            max_res <- this_res
            } else if (this_clusters < n_cluster) {
            min_res <- this_res
            } else {
            break
            }
            this_step <- this_step + 1    
        }
        Seurat_louvain <- Seurat::Idents(data_louvain)
        ### results
        cluster_predicted <- as.integer(Seurat_louvain)
        colnames(submat) <- as.character(cluster_predicted)
        cat(sprintf("%s cell clusters generated.\n", this_clusters))
    }
  return(list(clustering_result = cluster_predicted))
}

######################## Main Function for scATAC-seq ########################
## Test
# samplename <- "10X_ATAC_chr1_4194444_4399104.assigned.countmatrix"
# directory <- "/home/gayan/Projects/scATAC_Simulator/package_development/package_results/20230105_10X_scATACseq_INPUT"
# out_directory <- directory
# scATAC_runSyntheticCount(samplename, directory, out_directory)
## Read in count matrix
scATAC_runSyntheticCount <- function(samplename, directory, out_directory, n_cell_new="default", total_count_new="default", celllabel_file="default", n_cluster="default"){
  cat(sprintf("Reading count matrix %s.txt...\n", samplename))
  count_matrix <- read.table(sprintf("%s/%s.txt", directory, samplename), sep="\t",header = FALSE)
  matrix_num <- data.matrix(count_matrix[,2:ncol(count_matrix)])
  count_pergene_vec <- rowSums(matrix_num)
  # write.table(count_pergene_vec, sprintf("%s/%s.real.nPairsRegionmargional.txt",out_directory, samplename), row.names = FALSE,col.names = FALSE)
  matrix_num_nonzero <- matrix_num[count_pergene_vec>0,]
  ## Clustering
  if (celllabel_file == "default"){
    cat("No cell label file detected. Louvain clustering before simulation...\n")
    set.seed(2022)
    clustering_result <- get_cluster_seurat(matrix_num_nonzero, n_cluster=n_cluster)
    colnames(matrix_num) <- clustering_result$clustering_result
    write.table(clustering_result$clustering_result, sprintf("%s/%s.LouvainClusterResults.txt", out_directory, samplename), sep="\n", row.names = FALSE,col.names = FALSE)
  } else {
    cat(sprintf("Loading cell label file %s...\n", celllabel_file))
    clustering_result <- unlist(read.table(celllabel_file, header=FALSE))
    if (length(clustering_result) == ncol(matrix_num)){
    colnames(matrix_num) <- clustering_result
    } else {
      stop("Number of cell labels differs from the cell number contained in the count matrix!\n ")
    }
  }
  ## Use scDesign2 for training countmatrix
  cat("Model fitting...\n")
  n_cell_old <- ncol(matrix_num)
  total_count_old <- sum(matrix_num)
  if (n_cell_new == "default"){
    n_cell_new <- n_cell_old
  }
  if (total_count_new == "default"){
    total_count_new <- total_count_old
  }
  cell_type_sel <- unique(colnames(matrix_num))
  cell_type_prop <- table(colnames(matrix_num))[cell_type_sel]
  copula_result <- fit_model_scDesign2_new(matrix_num, cell_type_sel, sim_method = 'copula',
                                        ncores = length(cell_type_sel))
  cat("Generating synthetic count matrix...\n")
  cat(sprintf("Amount of synthetic cell: %s\n", n_cell_new))
  cat(sprintf("Amount of (expected) sequencing depth: %s\n", total_count_new))
  simu_matrix <- scDesign2::simulate_count_scDesign2(copula_result, 
                            total_count_old = total_count_old,
                            n_cell_old = n_cell_old,
                            total_count_new = total_count_new,
                            n_cell_new = n_cell_new,
                            cell_type_prop = cell_type_prop,
                            reseq_method = 'mean_scale', cell_sample = TRUE)

  write.table(colnames(simu_matrix), sprintf("%s/%s.scDesign2Simulated.CellTypeLabel.txt", out_directory, samplename), row.names = FALSE,col.names = FALSE)
  rownames(simu_matrix) <- count_matrix[,1]
  cat(sprintf("Writing out synthetic count matrix %s to %s...\n", out_directory, out_directory))
  write.table(simu_matrix, sprintf("%s/%s.scDesign2Simulated.txt", out_directory, samplename), sep="\t", row.names = TRUE,col.names = FALSE)
  cat("Done.\n")
}




# Test
# samplename <- "NGS_H2228_H1975_A549_H838_HCC827_Mixture_10X.COMPLE.UMIcountmatrix"
# directory <- "/home/guanao/Projects/scIsoSim/results/20230204"
# out_directory <- directory
# celllabel_file <- "/home/guanao/Projects/scIsoSim/results/20230204/NGS_H2228_H1975_A549_H838_HCC827_Mixture_10X.UMIcountmatrix.scDesign2Simulated.CellTypeLabel.txt"
# scRNA_runSyntheticCount(samplename, directory, out_directory, n_cluster=5, celllabel_file=celllabel_file)

######################## Main Function for scRNA-seq ########################
scRNA_runSyntheticCount <- function(samplename, directory, out_directory, n_cell_new="default", total_count_new="default", celllabel_file="default", n_cluster="default"){
  cat(sprintf("Reading count matrix %s.txt...\n", samplename))
  count_matrix <- read.table(sprintf("%s/%s.txt", directory, samplename), sep="\t",header = FALSE)
  matrix_num <- data.matrix(count_matrix[,2:ncol(count_matrix)])
  count_pergene_vec <- rowSums(matrix_num)
  matrix_num_nonzero <- matrix_num[count_pergene_vec>0,]

  ## Clustering
  if (celllabel_file == "default"){
    cat("No cell label file detected. Louvain clustering before simulation...\n")
    set.seed(2022)
    clustering_result <- get_cluster_seurat(matrix_num_nonzero, n_cluster=n_cluster)
    colnames(matrix_num) <- clustering_result$clustering_result
    write.table(clustering_result$clustering_result, sprintf("%s/%s.LouvainClusterResults.txt", out_directory, samplename), sep="\n", row.names = FALSE,col.names = FALSE)
  } else {
    cat(sprintf("Loading cell label file %s...\n", celllabel_file))
    clustering_result <- unlist(read.table(celllabel_file, header=FALSE))
    if (length(clustering_result) == ncol(matrix_num)){
    colnames(matrix_num) <- clustering_result
    } else {
      stop("Number of cell labels differs from the cell number contained in the count matrix! \n")
    }
  }
  ## Use scDesign2 for training countmatrix
  cat("Model fitting...\n")
  n_cell_old <- ncol(matrix_num)
  total_count_old <- sum(matrix_num)
  if (n_cell_new == "default"){
    n_cell_new <- n_cell_old
  }
  if (total_count_new == "default"){
    total_count_new <- total_count_old
  }
  cell_type_sel <- unique(colnames(matrix_num))
  cell_type_prop <- table(colnames(matrix_num))[cell_type_sel]
  copula_result <- fit_model_scDesign2_new(matrix_num, cell_type_sel, sim_method = 'copula',
                                        ncores = length(cell_type_sel))
  cat("Generating synthetic count matrix...\n")
  cat(sprintf("Amount of synthetic cell: %s\n", n_cell_new))
  cat(sprintf("Amount of (expected) sequencing depth: %s\n", total_count_new))
  # simu_matrix <- scDesign2::simulate_count_scDesign2(copula_result, n_cell_new, sim_method = 'copula',
  #                                                cell_type_prop = cell_type_prop)
  simu_matrix <- scDesign2::simulate_count_scDesign2(copula_result, 
                            total_count_old = total_count_old,
                            n_cell_old = n_cell_old,
                            total_count_new = total_count_new,
                            n_cell_new = n_cell_new,
                            cell_type_prop = cell_type_prop,
                            reseq_method = 'mean_scale', cell_sample = TRUE)
  rownames(simu_matrix) <- count_matrix[,1]
  write.table(colnames(simu_matrix), sprintf("%s/%s.scDesign2Simulated.CellTypeLabel.txt", out_directory, samplename), row.names = FALSE,col.names = FALSE)
  cat(sprintf("Writing out synthetic count matrix %s to %s...\n", out_directory, out_directory))
  write.table(simu_matrix, sprintf("%s/%s.scDesign2Simulated.txt", out_directory, samplename), sep="\t", row.names = TRUE,col.names = FALSE)
  cat("Done.\n")
}