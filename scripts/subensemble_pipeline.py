import os
from pathlib import Path
import shutil
import numpy as np
import torch
import pytorch_lightning as pl
from torchvision import transforms as torch_tfs
from torch.utils.data import random_split, DataLoader, Subset

from alg.dataloader import ALGDataset
from generate_subdataset import crop_dataset
from train_autoencoder import train_autoencoder
from train_subensemble import train_subensemble
from inference_subensemble import inference_subensemble
from test_subensemble import test_subensemble

def get_subdirs(dirname : str) -> list[str]:
    return [os.path.join(dirname, name) for name in os.listdir(dirname) if os.path.isdir(os.path.join(dirname, name))]

def copy_img_and_label(n : int | list, input_basedir : str, output_basedir : str, i_imgs : str = "input_images", i_labels : str = "mask_images", o_imgs : str = "images", o_labels : str = "labels", fext : str = ".tif"):
    input_imgdir = Path(input_basedir) / i_imgs
    input_labeldir = Path(input_basedir) / i_labels
    
    output_imgdir = Path(output_basedir) / o_imgs
    output_labeldir = Path(output_basedir) / o_labels

    if isinstance(n, int):
        img_list = list([x.stem for x in input_imgdir.glob("*" + fext)])
        img_ids = np.random.choice(img_list, n)
    else:
        img_ids = n
    
    for img_id in img_ids:
        inp_img_f = input_imgdir / (img_id + fext)
        inp_lab_f = input_labeldir / (img_id + fext)
        outp_img_f = output_imgdir / (img_id + fext)
        outp_lab_f = output_labeldir / (img_id + fext)
        shutil.copy2(inp_img_f, outp_img_f)
        shutil.copy2(inp_lab_f, outp_lab_f)
    print("Copied {} images and associated label files from: {} to: {}".format(
        len(img_ids), input_basedir, output_basedir
    ))

if __name__=="__main__":
    np.random.seed(0)
    pl.seed_everything(0)

    basedir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    datadir = os.path.join(basedir, 'data', 'reduced_example')
    sites_basedir = os.path.expanduser("~/src/csu/data/ALG/sites")
    sites_dirs = [
        os.path.join(sites_basedir, "site1_McD"),
        os.path.join(sites_basedir, "site2_GC"),
        os.path.join(sites_basedir, "site3_Kuma"),
        os.path.join(sites_basedir, "site4_TSR")
    ]
    # start with Site 1 - unlabeled images + 100 labeled images
    site_1_baseraw = os.path.join(sites_dirs[0], 'raw')
    site1_rawdirs = get_subdirs(site_1_baseraw)
    raw_root = os.path.join(datadir, 'raw')
    raw_output = os.path.join(raw_root, 'images')
    crop_dataset(site1_rawdirs, 1000, raw_output)

    # train autoencoder with unlabeled images
    use_subensemble = True # ! factor for strong baseline -> if false, will copy random images -> 
    base_logdir = os.path.join(basedir, 'lightning_logs', 'subensemble_pipeline' if use_subensemble else "baseline_select")
    # site_name = os.path.basename(sites_dirs[0])
    # ae_logdir = os.path.join(base_logdir, site_name, "ae")
    # autoencoder_path = train_autoencoder(32, raw_root, ae_logdir)
    # print("Trained Autoencoder at: {}".format(
    #     autoencoder_path
    # ))
    # autoencoder_paths = [autoencoder_path]

    # get subdataset for labeled heads training 
    labeled_output = os.path.join(datadir, 'labeled')
    # labeled_imgs = os.path.join(labeled_output, 'images')
    # labeled_labels = os.path.join(labeled_output, 'labels')    

    copy_img_and_label(100, sites_dirs[0], labeled_output)
    # train_subensembles - return position 0 is the autoencoder path, the others are the heads
    model_settings = {
        "epochs" : 200,          #! change back to 200
        "num_classes" : 1,
        "optim" : "adam",
        "lr" : 1e-3,
        "bs" : 16
    }
    # se_logdir = os.path.join(base_logdir, site_name)
    # subens_paths = train_subensemble(autoencoder_path, se_logdir, labeled_output, model_settings)

    load_true = True
    for site in sites_dirs[1:]:
        site_name = os.path.basename(site)
        print("Generating raw dataset for autoencoder training from site: {}".format(
            site_name
        ))

        # generate new raw dataset
        _rawdir = os.path.join(site, 'raw')
        input_rawdirs = get_subdirs(_rawdir)
        crop_dataset(input_rawdirs, 1000, raw_output)

        # train autoencoder - with previous data + "site"
        print("Completed copying dataset - Training autoencoder for site 0 and site: {}".format(
            site
        ))
        ae_logdir = os.path.join(base_logdir, site_name, "ae")
        autoenc_path = train_autoencoder(32, raw_root, ae_logdir)

        # train heads with dataset from sites-1 
        print("Completed training autoencoder - training subensemble heads on labeled dataset from sites previous to {}".format(
            site
        ))
        se_logdir = os.path.join(base_logdir, site_name)
        subens_paths = train_subensemble(autoenc_path, se_logdir, labeled_output, model_settings)

        # inference subensemble on site
        logd = os.path.join(base_logdir,"inference", site_name)
        site_p = os.path.join(site, "input_images") 
        print("Starting inference on site {} with models: {}.\nLogging to:{}".format(
            site_name, subens_paths, logd
        ))
        logd_test = os.path.join(base_logdir, "test", site_name)
        res = test_subensemble(subens_paths, site, model_settings, logd_test, img_folder="input_images", label_folder="mask_images")
        df = inference_subensemble(subens_paths, site, model_settings, logd,
                                img_folder="input_images", label_folder="mask_images",
                                load_true=load_true)

        # sort the label files
        df.sort_values('entropy', inplace=True, ascending=False)
        label_names = df.index[:20]
        
        # calculate the accuracy for the binary case
        if load_true:            # or: if "label" in df.columns
            acc = (df["vote"] ==df["label"]).mean()
            print("Accuracy: for site: {}: {}".format(site_name, acc))

        # copy the files
        copy_img_and_label(label_names if use_subensemble else 20, site, labeled_output)        