import 'dart:io';
import 'dart:typed_data';
import 'package:demo_ai_even/ble_manager.dart';
import 'package:demo_ai_even/controllers/bmp_update_manager.dart';
import 'package:demo_ai_even/services/proto.dart';
import 'package:demo_ai_even/utils/utils.dart';

class FeaturesServices {
  final bmpUpdateManager = BmpUpdateManager();
  Future<void> sendBmp(String imageUrl) async {
    Uint8List bmpData = await Utils.loadBmpImage(imageUrl);
    int initialSeq = 0;
    bool isSuccess = await Proto.sendHeartBeat();
    print("${DateTime.now()} testBMP -------startSendBeatHeart----isSuccess---$isSuccess------");
    BleManager.get().startSendBeatHeart();

    final results = await Future.wait([
      bmpUpdateManager.updateBmp("L", bmpData, seq: initialSeq),
      bmpUpdateManager.updateBmp("R", bmpData, seq: initialSeq)
    ]);

    bool successL = results[0];
    bool successR = results[1];

    if (successL) {
      print("${DateTime.now()} left ble success");
    } else {
      print("${DateTime.now()} left ble fail");
    }

    if (successR) {
      print("${DateTime.now()} right ble success");
    } else {
      print("${DateTime.now()} right ble success");
    }
  }

  Future<void> sendBinocularBmps(String imageUrlLeft, String imageUrlRight) async {
    Uint8List bmpDataL = await Utils.loadBmpImage(imageUrlLeft);
    Uint8List bmpDataR = await Utils.loadBmpImage(imageUrlRight);

    int initialSeq = 0;
    bool isSuccess = await Proto.sendHeartBeat();
    print("${DateTime.now()} testBMP -------startSendBeatHeart----isSuccess---$isSuccess------");
    BleManager.get().startSendBeatHeart();

    final results = await Future.wait([
      bmpUpdateManager.updateBmp("L", bmpDataL, seq: initialSeq),
      bmpUpdateManager.updateBmp("R", bmpDataR, seq: initialSeq)
    ]);

    bool successL = results[0];
    bool successR = results[1];

    if (successL) {
      print("${DateTime.now()} left ble success");
    } else {
      print("${DateTime.now()} left ble fail");
    }

    if (successR) {
      print("${DateTime.now()} right ble success");
    } else {
      print("${DateTime.now()} right ble success");
    }
  }

  Future<void> sendSingleBmp(File file, bool isLeft) async {
    File bmpFile = file;
    Uint8List bmpData = await bmpFile.readAsBytes();

    int initialSeq = 0;

    // todo address dynamic
    bool result = await bmpUpdateManager.updateBmp(isLeft ? 'L' : "R", bmpData, seq: initialSeq);
    print("sendSingleBmp-----result----$result------bmpData----${bmpData.length}----");
  }


  Future<void> exitBmp() async {
    bool isSuccess = await Proto.exit();
    print("exitBmp----isSuccess---$isSuccess--");
  }
}