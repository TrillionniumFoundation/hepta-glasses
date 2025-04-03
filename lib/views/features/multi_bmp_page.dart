import 'dart:io';
import 'dart:typed_data';

import 'package:demo_ai_even/ble_manager.dart';
import 'package:demo_ai_even/controllers/bmp_update_manager.dart';
import 'package:demo_ai_even/services/features_services.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';

class MultiBmpPage extends StatefulWidget {
  const MultiBmpPage({super.key});

  @override
  _MultiBmpPageState createState() => _MultiBmpPageState();
}

class _MultiBmpPageState extends State<MultiBmpPage> {
  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          title: const Text('BMP Demo'),
        ),
        body: Padding(
          padding:
              const EdgeInsets.only(left: 16, right: 16, top: 12, bottom: 44),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.start,
            children: [
              GestureDetector(
                onTap: () async {
                  MultiBmpPage().pickAndSaveBmpFiles();
                  return;
                  if (BleManager.get().isConnected == false) return;
                  FeaturesServices().sendBmp("assets/images/image_1.bmp");
                },
                child: Container(
                  height: 60,
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(5),
                  ),
                  alignment: Alignment.center,
                  child: const Text("Left", style: TextStyle(fontSize: 16)),
                ),
              ),
              const SizedBox(height: 16),
              GestureDetector(
                onTap: () async {
                  MultiBmpPage().pickAndSaveBmpFiles();
                  return;
                  if (BleManager.get().isConnected == false) return;
                  FeaturesServices().sendBmp("assets/images/image_2.bmp");
                },
                child: Container(
                  height: 60,
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(5),
                  ),
                  alignment: Alignment.center,
                  child: const Text("Right", style: TextStyle(fontSize: 16)),
                ),
              ),

              const SizedBox(height: 16),
              GestureDetector(
                onTap: () async {
                  if (BleManager.get().isConnected == false) return;
                  FeaturesServices().exitBmp(); // todo
                },
                child: Container(
                  height: 60,
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(5),
                  ),
                  alignment: Alignment.center,
                  child: const Text("Exit", style: TextStyle(fontSize: 16)),
                ),
              ),
            ],
          ),
        ),
      );
}

extension DataMethods on MultiBmpPage {
  Future<void> pickAndSaveBmpFiles() async {
    FilePickerResult? result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['bmp'], 
      allowMultiple: true, // 允许多选
    );

    if (result != null) {
      List<File> files = result.paths.map((path) => File(path!)).toList();
      print("pickAndSaveBmpFiles-------files------${files.length}");
    
      if (files.length > 10) {
        debugPrint("最多只能选择 10 张 BMP 图片");
        return;
      }
      
      
      for (int i = 0; i < files.length; i++) {
        //await saveBmpFile(files[i], i + 1); // 给文件添加顺序编号
        print("${DateTime.now()} pickAndSaveBmpFiles-----i-------$i------");
        //await FeaturesServices().sendBmpSingleBle(files[i], true);
        await FeaturesServices().sendSingleBmp(files[i], true);
      }
      
    } else {
      debugPrint("用户未选择文件");
    }  
  }

  Future<void> saveBmpFile(File bmpFile, int index) async {
    debugPrint("saveBmpFile-----index----$index-----bmpFile-----${bmpFile.length()}------");

    Directory dir = await getApplicationDocumentsDirectory();
    String newPath = "${dir.path}/image_${index.toString().padLeft(2, '0')}.bmp";
    await bmpFile.copy(newPath);
    debugPrint("BMP 图片已保存: $newPath");
  }
}