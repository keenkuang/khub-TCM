import 'package:flutter/material.dart';
import '../api/khub_api.dart';

class TwinPage extends StatefulWidget {
  _TwinPageState createState() => _TwinPageState();
}
class _TwinPageState extends State<TwinPage> {
  Map _twin = {};

  void initState() { super.initState(); _load(); }

  Future<void> _load() async {
    try {
      final r = await KhubApi.get('/twin/1');
      setState(() => _twin = r);
    } catch (_) {}
  }

  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: Text('健康摘要')),
    body: ListView(
      children: [
        Card(child: Padding(padding: EdgeInsets.all(16), child: Text(_twin['summary'] ?? '暂无摘要'))),
        if (_twin['timeline'] != null)
          ...(_twin['timeline'] as List).map((t) => Card(
            child: ListTile(title: Text('${t['date']} [${t['type']}]'), subtitle: Text(t['summary'] ?? '')))),
      ],
    ),
  );
}
