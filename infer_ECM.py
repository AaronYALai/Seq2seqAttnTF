# -*- coding: utf-8 -*-
# @Author: aaronlai
# @Date:   2018-05-15 00:04:50
# @Last Modified by:   AaronLai
# @Last Modified time: 2018-06-01 22:29:10

from utils import init_embeddings, compute_ECM_loss, get_ECM_config, \
                  loadfile, load

import argparse
import yaml
import tensorflow as tf
import numpy as np
import pandas as pd


def parse_args():
    '''
    Parse Emotional Chatting Machine arguments.
    '''
    parser = argparse.ArgumentParser(description="Run ECM inference.")

    parser.add_argument('--config', nargs='?',
                        default='./configs/config_ECM.yaml',
                        help='Configuration file for model specifications')

    return parser.parse_args()


def main(args):
    # loading configurations
    with open(args.config) as f:
        config = yaml.safe_load(f)["configuration"]

    name = config["Name"]

    # Construct or load embeddings
    print("Initializing embeddings ...")
    vocab_size = config["embeddings"]["vocab_size"]
    embed_size = config["embeddings"]["embed_size"]
    embeddings = init_embeddings(vocab_size, embed_size, name=name)
    print("\tDone.")

    # Build the model and compute losses
    source_ids = tf.placeholder(tf.int32, [None, None], name="source")
    target_ids = tf.placeholder(tf.int32, [None, None], name="target")
    sequence_mask = tf.placeholder(tf.bool, [None, None], name="mask")
    choice_qs = tf.placeholder(tf.float32, [None, None], name="choice")
    emo_cat = tf.placeholder(tf.int32, [None], name="emotion_category")

    (enc_num_layers, enc_num_units, enc_cell_type, enc_bidir,
     dec_num_layers, dec_num_units, dec_cell_type, state_pass,
     num_emo, emo_cat_units, emo_int_units,
     infer_batch_size, beam_size, max_iter,
     attn_num_units, l2_regularize) = get_ECM_config(config)

    print("Building model architecture ...")
    CE, loss, train_outs, infer_outputs = compute_ECM_loss(
        source_ids, target_ids, sequence_mask, choice_qs, embeddings,
        enc_num_layers, enc_num_units, enc_cell_type, enc_bidir,
        dec_num_layers, dec_num_units, dec_cell_type, state_pass,
        num_emo, emo_cat, emo_cat_units, emo_int_units, infer_batch_size,
        beam_size, max_iter, attn_num_units, l2_regularize, name)
    print("\tDone.")

    # Set up session
    restore_from = config["training"]["restore_from"]
    gpu_fraction = config["training"]["gpu_fraction"]
    gpu_options = tf.GPUOptions(per_process_gpu_memory_fraction=gpu_fraction)
    sess = tf.Session(config=tf.ConfigProto(log_device_placement=False,
                                            gpu_options=gpu_options))
    init = tf.global_variables_initializer()
    sess.run(init)

    # Saver for storing checkpoints of the model.
    saver = tf.train.Saver(var_list=tf.trainable_variables())

    try:
        saved_global_step = load(saver, sess, restore_from)
        if saved_global_step is None:
            raise ValueError("Cannot find the checkpoint to restore from.")

    except Exception:
        print("Something went wrong while restoring checkpoint. ")
        raise

    # ##### Inference #####
    # Load data
    print("Loading inference data ...")

    # id_0, id_1, id_2 preserved for SOS, EOS, constant zero padding
    embed_shift = 3
    filename = config["inference"]["infer_source_file"]
    c_filename = config["inference"]["infer_category_file"]
    max_leng = config["inference"]["infer_source_max_length"]

    source_data = loadfile(filename, is_source=True,
                           max_length=max_leng) + embed_shift
    category_data = pd.read_csv(
        c_filename, header=None, index_col=None, dtype=int)[0].values
    print("\tDone.")

    # Inference
    print("Start inferring ...")
    final_result = []
    n_data = source_data.shape[0]
    n_pad = n_data % infer_batch_size
    if n_pad > 0:
        n_pad = infer_batch_size - n_pad

    pad = np.zeros((n_pad, max_leng), dtype=np.int32)
    source_data = np.concatenate((source_data, pad))
    category_data = np.concatenate((category_data, np.zeros(n_pad)))

    for ith in range(int(len(source_data) / infer_batch_size)):
        start = ith * infer_batch_size
        end = (ith + 1) * infer_batch_size
        batch = source_data[start:end]
        batch_cat = category_data[start:end]

        result = sess.run(infer_outputs,
                          feed_dict={source_ids: batch, emo_cat: batch_cat})
        result = result.ids[:, :, 0]

        if result.shape[1] < max_iter:
            l_pad = max_iter - result.shape[1]
            result = np.concatenate(
                (result, np.ones((infer_batch_size, l_pad))), axis=1)

        final_result.append(result)

    final_result = np.concatenate(final_result)[:n_data] - embed_shift
    choice_pred = (final_result >= vocab_size).astype(np.int)
    final_result[final_result >= vocab_size] -= (vocab_size + embed_shift)

    # transform to output format
    final_result[final_result < 0] = -1
    final_result = (final_result.astype(int)).astype(str).tolist()
    final_result = list(map(lambda t: " ".join(t), final_result))

    choice_pred = choice_pred.astype(str).tolist()
    choice_pred = list(map(lambda t: " ".join(t), choice_pred))

    df = pd.DataFrame(data={"0": final_result})
    df.to_csv(config["inference"]["output_path"], header=None, index=None)

    cdf = pd.DataFrame(data={"0": choice_pred})
    cdf.to_csv(config["inference"]["choice_path"], header=None, index=None)
    print("\tDone.")


if __name__ == "__main__":
    args = parse_args()
    main(args)
