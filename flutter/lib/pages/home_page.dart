import 'package:flutter/material.dart';
import '../api/khub_api.dart';
import 'dart:convert';
import 'package:shared_preferences/shared_preferences.dart';

class HomePage extends StatefulWidget {
  _HomePageState createState() => _HomePageState();
}
class _HomePageState extends State<HomePage> {
  String? _role;
  Map _stats = {};

  void initState() { super.initState(); _load(); }

  Future<void> _load() async {
    final prefs = await SharedPreferences.getInstance();
    final userStr = prefs.getString('khub_user');
    if (userStr != null) _role = jsonDecode(userStr)['role'];
    try { final s = await KhubApi.get('/stats'); _stats = s; } catch (_) {}
    setState(() {});
  }

  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: Text('kHUB'), actions: [
      if (_role == 'doctor' || _role == 'admin')
        TextButton(onPressed: () => Navigator.pushNamed(context, '/patients'), child: Text('患者')),
    ]),
    body: ListView(
      children: [
        _card(context, '预约管理', Icons.calendar_month, '/appointments'),
        _card(context, '健康摘要', Icons.health_and_safety, '/twin'),
        _card(context, '健康趋势', Icons.trending_up, '/trends'),
        if (_stats.isNotEmpty) ...[
          Divider(),
          Text('概览  ${_stats['total'] ?? 0} 文档', style: Theme.of(context).textTheme.titleSmall),
          Text('今日 ${_stats['today'] ?? 0} 入库'),
        ],
      ],
    ),
  );

  Widget _card(BuildContext c, String t, IconData i, String r) => Card(
    child: ListTile(leading: Icon(i), title: Text(t), trailing: Icon(Icons.chevron_right),
      onTap: () => Navigator.pushNamed(c, r)));
}
