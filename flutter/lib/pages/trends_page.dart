import 'package:flutter/material.dart';
import '../api/khub_api.dart';

class TrendsPage extends StatefulWidget {
  _TrendsPageState createState() => _TrendsPageState();
}
class _TrendsPageState extends State<TrendsPage> {
  Map _trends = {};

  void initState() { super.initState(); _load(); }

  Future<void> _load() async {
    try { final r = await KhubApi.get('/clinical/trends/1'); setState(() => _trends = r['trends'] ?? r); } catch (_) {}
  }

  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: Text('健康趋势')),
    body: ListView(
      children: [
        Card(child: Padding(padding: EdgeInsets.all(16), child: Text('体质画像: ${_trends['body_constitution'] ?? '暂无'}'))),
        if (_trends['syndrome_evolution'] != null)
          ...(_trends['syndrome_evolution'] as List).map((e) => Card(
            child: ListTile(title: Text('${e['date']}'), subtitle: Text(e['differentiation'] ?? '')))),
      ],
    ),
  );
}
