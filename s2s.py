#!/usr/bin/env python3
import requests
import os
import sys
import math
import time

import numpy as np
import tensorflow as tf

import data_utils
import s2s_model

import time
import telepot
from telepot.loop import MessageLoop
from telepot.namedtuple import InlineKeyboardMarkup, InlineKeyboardButton
from telepot.namedtuple import ReplyKeyboardMarkup
import mysql.connector
import datetime
import json

from telepot.namedtuple import InlineQueryResultArticle, InputTextMessageContent



class DateEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime.datetime):
            return obj.strftime('%Y-%m-%d %H:%M:%S')
        elif isinstance(obj, date):
            return obj.strftime("%Y-%m-%d")
        else:
            return json.JSONEncoder.default(self, obj)


tf.app.flags.DEFINE_float(
    'learning_rate',
    0.0003,
    '學習率'
)
tf.app.flags.DEFINE_float(
    'max_gradient_norm',
    5.0,
    '梯度最大閾值'
)
tf.app.flags.DEFINE_float(
    'dropout',
    1.0,
    '每層輸出DROPOUT的大小'
)
tf.app.flags.DEFINE_integer(
    'batch_size',
    64,
    '批量梯度下降的批量大小'
)
tf.app.flags.DEFINE_integer(
    'size',
    512,
    'LSTM每層神經元數量'
)
tf.app.flags.DEFINE_integer(
    'num_layers',
    2,
    'LSTM的層數'
)
tf.app.flags.DEFINE_integer(
    'num_epoch',
    5,
    '訓練幾輪'
)
tf.app.flags.DEFINE_integer(
    'num_samples',
    512,
    '分批softmax的樣本量'
)
tf.app.flags.DEFINE_integer(
    'num_per_epoch',
    10000,
    '每輪訓練多少隨機樣本'
)
tf.app.flags.DEFINE_string(
    'buckets_dir',
    './bucket_dbs',
    'sqlite3數據庫所在文件夾'
)
tf.app.flags.DEFINE_string(
    'model_dir',
    './model',
    '模型保存的目錄'
)
tf.app.flags.DEFINE_string(
    'model_name',
    'model',
    '模型保存的名稱'
)
tf.app.flags.DEFINE_boolean(
    'use_fp16',
    False,
    '是否使用16位浮點數（默認32位）'
)
tf.app.flags.DEFINE_integer(
    'bleu',
    -1,
    '是否測試bleu'
)
tf.app.flags.DEFINE_boolean(
    'test',
    False,
    '是否在測試'
)

FLAGS = tf.app.flags.FLAGS
buckets = data_utils.buckets


def create_model(session, forward_only):
    """建立模型"""
    dtype = tf.float16 if FLAGS.use_fp16 else tf.float32
    model = s2s_model.S2SModel(
        data_utils.dim,
        data_utils.dim,
        buckets,
        FLAGS.size,
        FLAGS.dropout,
        FLAGS.num_layers,
        FLAGS.max_gradient_norm,
        FLAGS.batch_size,
        FLAGS.learning_rate,
        FLAGS.num_samples,
        forward_only,
        dtype
    )
    return model

# train-----------------------------------------------------------------------------------------
def train():
    """訓練模型"""
    # 準備數據
    print("train mode")
    print('準備數據')
    if not os.path.exists(FLAGS.model_dir):
        os.makedirs(FLAGS.model_dir)
    bucket_dbs = data_utils.read_bucket_dbs(FLAGS.buckets_dir)
    bucket_sizes = []
    for i in range(len(buckets)):
        bucket_size = bucket_dbs[i].size
        bucket_sizes.append(bucket_size)
        print('bucket {} 中有數據 {} 條'.format(i, bucket_size))
    total_size = sum(bucket_sizes)
    print('共有數據 {} 條'.format(total_size))
    # 開始建模與訓練
    with tf.Session() as sess:
        #　構建模型
        model = create_model(sess, False)
        # 初始化變量
        sess.run(tf.initialize_all_variables())
        ckpt = tf.train.get_checkpoint_state(FLAGS.model_dir)
        #print("ckpt path : ", ckpt.model_checkpoint_path)
        if ckpt != None:
            print("load old model : ", ckpt.model_checkpoint_path)
            model.saver.restore(sess, ckpt.model_checkpoint_path)
        else:
            print("not exist old model")
        buckets_scale = [
            sum(bucket_sizes[:i + 1]) / total_size
            for i in range(len(bucket_sizes))
        ]
        # 開始訓練
        metrics = '  '.join([
            '\r[{}]',
            '{:.1f}%',
            '{}/{}',
            'loss={:.3f}',
            '{}/{}'
        ])
        bars_max = 20
        for epoch_index in range(1, FLAGS.num_epoch + 1):
            print('Epoch {}:'.format(epoch_index))
            time_start = time.time()
            epoch_trained = 0
            batch_loss = []
            while True:
                # 選擇一個要訓練的bucket
                random_number = np.random.random_sample()
                bucket_id = min([
                    i for i in range(len(buckets_scale))
                    if buckets_scale[i] > random_number
                ])
                data, data_in = model.get_batch_data(
                    bucket_dbs,
                    bucket_id
                )
                encoder_inputs, decoder_inputs, decoder_weights = model.get_batch(
                    bucket_dbs,
                    bucket_id,
                    data
                )
                _, step_loss, output = model.step(
                    sess,
                    encoder_inputs,
                    decoder_inputs,
                    decoder_weights,
                    bucket_id,
                    False
                )
                epoch_trained += FLAGS.batch_size
                batch_loss.append(step_loss)
                time_now = time.time()
                time_spend = time_now - time_start
                time_estimate = time_spend / \
                    (epoch_trained / FLAGS.num_per_epoch)
                percent = min(100, epoch_trained / FLAGS.num_per_epoch) * 100
                bars = math.floor(percent / 100 * bars_max)
                sys.stdout.write(metrics.format(
                    '=' * bars + '-' * (bars_max - bars),
                    percent,
                    epoch_trained, FLAGS.num_per_epoch,
                    np.mean(batch_loss),
                    data_utils.time(time_spend), data_utils.time(time_estimate)
                ))
                sys.stdout.flush()
                if epoch_trained >= FLAGS.num_per_epoch:
                    model.saver.save(sess, os.path.join(
                        FLAGS.model_dir, FLAGS.model_name), global_step=epoch_index)
                    break
            print('\n')


# connect db------------------------------------------------------------------------------
db = mysql.connector.connect(
    host="140.131.114.151",
    user="teleberry03",
    password="teleberry110503",
    database="teleberry03",
    port="3306",
    buffered=True,
)

# play-----------------------------------------------------------------------------------------
def play():
    # push message-----------------------------------------------------------------------------------
    # mycursor = db.cursor()
    # mycursor.execute(
    #     'SELECT cabnum FROM `teleberry03`.picmsg where statu = "1";')
    # myresult = mycursor.fetchone()

    # if myresult:

    #     print(myresult)

    #     r = requests.post(
    #         f"https://api.telegram.org/bot2142626601:AAGI4thiimWFzT4P6ynSfAJbjwDBU2UMcSI/sendMessage",
    #         json={
    #             "chat_id": "1318965520",
    #             "text": "!!!紅色警戒!!!\n" + str(myresult[0]) + "機櫃發生異常",
    #         })
    # ------------------------------------------------------------------------------

    print("play mode")

    class TestBucket(object):
        def __init__(self, sentence):
            self.sentence = sentence

        def random(self):
            return self.sentence, ''

    with tf.Session() as sess:
        #　構建模型
        model = create_model(sess, True)
        model.batch_size = 1
        # 初始化變量
        sess.run(tf.initialize_all_variables())

        ckpt = tf.train.get_checkpoint_state(FLAGS.model_dir)
        model.saver.restore(sess, ckpt.model_checkpoint_path)

    # sen-----------------------------------------------------------------------------------------
        def sen(sentence):
            print("in sentence------------------------------------------------")
            print(sentence)
            bucket_id = min([
                b for b in range(len(buckets))
                if buckets[b][0] > len(sentence)
            ])
            data, _ = model.get_batch_data(
                {bucket_id: TestBucket(sentence)},
                bucket_id
            )
            encoder_inputs, decoder_inputs, decoder_weights = model.get_batch(
                {bucket_id: TestBucket(sentence)},
                bucket_id,
                data
            )
            _, _, output_logits = model.step(
                sess,
                encoder_inputs,
                decoder_inputs,
                decoder_weights,
                bucket_id,
                True
            )
            outputs = [int(np.argmax(logit, axis=1))
                       for logit in output_logits]
            ret = data_utils.indice_sentence(outputs)
            return ret

        
    # handle-----------------------------------------------------------------------------------------
        def handle(msg):
            sentence = msg['text']
            print("in handle------------------------------------------------")
            content_type, chat_type, chat_id = telepot.glance(msg)
            print(content_type, chat_type, chat_id)
            print(f"{msg}------------------------------------------------")

            if msg['text'] == '/start':
                bot.sendMessage(
                    chat_id, text='歡迎來到 TeleBerry 機房監控系統!\n輸入/check查詢設備狀態，或是輸入任意文字跟我聊天~')
            elif msg['text'] == '/check':
                mark_up = ReplyKeyboardMarkup(
                    keyboard=[['查詢設備當前狀況'], ['查詢設備歷史狀況']], one_time_keyboard=True)
                bot.sendMessage(
                    chat_id, text='請選擇當前查詢或歷史查詢', reply_markup=mark_up)
            elif msg['text'] == '查詢設備當前狀況':
                mark_up = ReplyKeyboardMarkup(
                    keyboard=[['A07'], ['A08']], one_time_keyboard=True)
                bot.sendMessage(chat_id, '請輸入欲查詢的設備代號', reply_markup=mark_up)

        # 歷史-----------------------------------------------------------------------------------------
            elif msg['text'] == '查詢設備歷史狀況':
                mark_up = ReplyKeyboardMarkup(
                    keyboard=[['A07歷史'], ['A08歷史']], one_time_keyboard=True)
                bot.sendMessage(chat_id, '請輸入欲查詢的設備代號', reply_markup=mark_up)

            elif msg['text'] == 'A07歷史':
                mycursor = db.cursor()
                json.dumps(mycursor.execute(
                    'SELECT time FROM `teleberry03`.picmsg where cabnum = "A07";'), cls=DateEncoder)
                myresult = mycursor.fetchall()

                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=json.dumps((myresult[0]), cls=DateEncoder), callback_data="a")],
                    [InlineKeyboardButton(text=json.dumps((myresult[1]), cls=DateEncoder), callback_data="b")],
                ])
                bot.sendMessage(chat_id, '請從下方選擇欲查詢的日期', reply_markup=keyboard)
                
            elif msg['text'] == 'A08歷史':
                mycursor = db.cursor()
                json.dumps(mycursor.execute(
                    'SELECT time FROM `teleberry03`.picmsg where cabnum = "A08";'), cls=DateEncoder)
                myresult = mycursor.fetchall()

                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=json.dumps((myresult[0]), cls=DateEncoder), callback_data="a")],
                    [InlineKeyboardButton(text=json.dumps((myresult[1]), cls=DateEncoder), callback_data="b")],
                ])
                bot.sendMessage(chat_id, '請從下方選擇欲查詢的日期', reply_markup=keyboard)

                
        # 當前-----------------------------------------------------------------------------------------
            elif msg['text'] == 'A07':
                mycursor = db.cursor()
                mycursor.execute(
                    'SELECT statu FROM `teleberry03`.picmsg where cabnum = "A07" order by time desc;')
                myresult = mycursor.fetchone()
                bot.sendMessage(chat_id, "A07當前機櫃狀態為" +
                                str(myresult[0])+" "+"(1為異常，0為正常)")
            elif msg['text'] == 'A08':
                mycursor = db.cursor()
                mycursor.execute(
                    'SELECT statu FROM `teleberry03`.picmsg where cabnum = "A08" order by time desc;')
                myresult = mycursor.fetchone()
                bot.sendMessage(chat_id, "A08當前機櫃狀態為" +
                                str(myresult[0])+" "+"(1為異常，0為正常)")

            elif msg['text'] == '/click':
                bot.sendMessage(
                    chat_id, "https://orteil.dashnet.org/cookieclicker/")

        # 日常-----------------------------------------------------------------------------------------
            else:
                sen(sentence)

                bot.sendMessage(chat_id, sen(sentence))
    # run bot-----------------------------------------------------------------------------------------
        TOKEN = '2142626601:AAGI4thiimWFzT4P6ynSfAJbjwDBU2UMcSI'

        bot = telepot.Bot(TOKEN)

        MessageLoop(bot, handle).run_as_thread()

        while 1:
            time.sleep(10)


# 執行程式-----------------------------------------------------------------------------------------

def main(_):
    if FLAGS.test:
        play()
    else:
        train()


if __name__ == '__main__':
    np.random.seed(0)
    tf.set_random_seed(0)
    tf.app.run()
