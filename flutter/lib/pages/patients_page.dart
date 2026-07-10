import 'package:flutter/material.dart';
import '../api/khub_api.dart';

class PatientsPage extends StatefulWidget {
  _PatientsPageState createState() => _PatientsPageState();
}
class _PatientsPageState extends State<PatientsPage> {
  List _patients = [];

  void initState() { super.initState(); _load(); }

  Future<void> _load() async {
    try { final r = await KhubApi.get('/clinical/patients'); setState(() => _patients = r['patients'] ?? []); } catch (_) {}
  }

  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: Text('患者')),
    body: ListView.builder(
      itemCount: _patients.length,
      itemBuilder: (_, i) => ListTile(
        title: Text(_patients[i]['name'] ?? ''),
        subtitle: Text('#${_patients[i]['id']}'),
        onTap: () => Navigator.pushNamed(context, '/twin'),
      ),
    ),
  );
}
