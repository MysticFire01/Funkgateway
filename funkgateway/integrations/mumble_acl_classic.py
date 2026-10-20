"""Mumble-style groups and ACL editing atop the existing server-gated editor."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
 QTabWidget,QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QGroupBox,QLabel,
 QListWidget,QListWidgetItem,QComboBox,QCheckBox,QPushButton,QInputDialog,
 QMessageBox,QScrollArea,QFormLayout,QLineEdit,QSpinBox,QTextEdit
)
from .mumble_acl_dialog import MumbleAclDialog,PERMISSIONS

class MumbleAclClassicDialog(MumbleAclDialog):
    def __init__(self,client,channel_id,channel_name,parent=None):
        super().__init__(client,channel_id,channel_name,parent)
        self.resize(980,700)
        old_tabs=self.findChildren(QTabWidget)[0]
        old_tabs.hide()
        self.member_add.hide()
        self._selected_group=-1
        self._selected_rule=-1
        body=QTabWidget(self)
        self.layout().insertWidget(self.layout().count()-1,body,1)
        self._build_properties(body)
        self._build_groups(body)
        self._build_rules(body)
        self.inherit.stateChanged.connect(self._update_rule_details)

    def _clear(self):
        super()._clear()
        if hasattr(self,"group_select"):
            self.group_select.clear()
            for widget in (self.inherited_members,self.rule_list):
                widget.clear()
            for widget,_col in self.group_lists:
                widget.clear()
            self._selected_group=-1
            self._selected_rule=-1
            self._update_rule_details()

    def _build_properties(self,body):
        page=QWidget()
        form=QFormLayout(page)
        details=self.client.channel_details(self.channel_id)
        self.property_name=QLineEdit(str(details.get("name") or ""))
        self.property_name.setReadOnly(self.channel_id==0)
        self.property_description=QTextEdit()
        self.property_description.setPlainText(str(details.get("description") or ""))
        self.property_position=QSpinBox()
        self.property_position.setRange(-100000,100000)
        self.property_position.setValue(int(details.get("position") or 0))
        self.property_position.setEnabled(self.channel_id!=0)
        self.property_save=QPushButton("Raumeigenschaften speichern")
        self.property_save.clicked.connect(self._save_properties)
        form.addRow("Name:",self.property_name)
        form.addRow("Beschreibung:",self.property_description)
        form.addRow("Position:",self.property_position)
        form.addRow("Raum-ID:",QLabel(str(self.channel_id)))
        form.addRow("",self.property_save)
        form.addRow("",QLabel("Der Mumble-Server prüft alle Änderungen anhand deiner Rechte."))
        body.addTab(page,"Eigenschaften")

    def _save_properties(self):
        name=self.property_name.text().strip()
        if not name:
            QMessageBox.warning(self,"Mumble","Der Raumname darf nicht leer sein.")
            return
        try:
            self.client.edit_channel(self.channel_id,name,
                self.property_description.toPlainText(),self.property_position.value())
            QMessageBox.information(self,"Mumble","Änderung an den Server gesendet. Der Server prüft die Rechte.")
        except Exception as exc:
            QMessageBox.warning(self,"Mumble – Raumeigenschaften",str(exc))

    def _build_groups(self,body):
        page=QWidget()
        v=QVBoxLayout(page)
        bar=QHBoxLayout()
        bar.addWidget(QLabel("Gruppe:"))
        self.group_select=QComboBox()
        self.group_select.currentIndexChanged.connect(self._select_group)
        bar.addWidget(self.group_select,1)
        add=QPushButton("Hinzufügen")
        remove=QPushButton("Entfernen")
        add.clicked.connect(self._create_group)
        remove.clicked.connect(self._remove_group)
        bar.addWidget(add);bar.addWidget(remove)
        v.addLayout(bar)
        flags=QHBoxLayout()
        self.group_inherit=QCheckBox("Erben")
        self.group_inheritable=QCheckBox("Vererbbar")
        self.group_inherit.stateChanged.connect(self._store_group)
        self.group_inheritable.stateChanged.connect(self._store_group)
        flags.addWidget(self.group_inherit)
        flags.addWidget(self.group_inheritable)
        flags.addStretch()
        v.addLayout(flags)
        row=QHBoxLayout()
        self.group_lists=[]
        for title,col in (("Mitglieder",1),("Ausgeschlossene Mitglieder",2)):
            frame=QGroupBox(title)
            f=QVBoxLayout(frame)
            lst=QListWidget()
            f.addWidget(lst,1)
            controls=QHBoxLayout()
            add_button=QPushButton("Mitglied hinzufügen …")
            remove_button=QPushButton("Entfernen")
            add_button.clicked.connect(lambda _=False,c=col:self._group_add_user(c))
            remove_button.clicked.connect(lambda _=False,c=col,l=lst:self._group_remove_user(c,l))
            controls.addWidget(add_button)
            controls.addWidget(remove_button)
            f.addLayout(controls)
            row.addWidget(frame,1)
            self.group_lists.append((lst,col))
        inherited=QGroupBox("Geerbte Mitglieder")
        box=QVBoxLayout(inherited)
        self.inherited_members=QListWidget()
        box.addWidget(self.inherited_members)
        exclude_button=QPushButton("Ausgewähltes Mitglied ausschließen")
        exclude_button.clicked.connect(self._exclude_inherited_member)
        box.addWidget(exclude_button)
        row.addWidget(inherited,1)
        v.addLayout(row,1)
        body.addTab(page,"Gruppen")

    def _build_rules(self,body):
        page=QWidget()
        v=QHBoxLayout(page)
        left=QVBoxLayout()
        title=QLabel("Aktive Berechtigungen (Reihenfolge)")
        left.addWidget(title)
        self.rule_list=QListWidget()
        self.rule_list.currentRowChanged.connect(self._select_rule)
        left.addWidget(self.rule_list,1)
        controls=QHBoxLayout()
        for name,cb in (("Hoch",lambda:self._move_rule(-1)),
                        ("Runter",lambda:self._move_rule(1)),
                        ("Hinzufügen",self._create_rule),
                        ("Entfernen",self._remove_rule)):
            btn=QPushButton(name);btn.clicked.connect(cb);controls.addWidget(btn)
        left.addLayout(controls)
        context=QGroupBox("Kontext")
        cf=QVBoxLayout(context)
        self.rule_here=QCheckBox("Betrifft diesen Raum")
        self.rule_subs=QCheckBox("Betrifft Unterräume")
        self.rule_here.stateChanged.connect(self._store_rule)
        self.rule_subs.stateChanged.connect(self._store_rule)
        cf.addWidget(self.rule_here);cf.addWidget(self.rule_subs)
        left.addWidget(context)
        target=QGroupBox("Benutzer / Gruppe")
        tf=QVBoxLayout(target)
        self.rule_target=QComboBox()
        self.rule_target.setEditable(True)
        self.rule_target.addItem("all")
        self.rule_target.lineEdit().editingFinished.connect(self._store_rule)
        self.rule_target.activated.connect(self._store_rule)
        tf.addWidget(self.rule_target)
        left.addWidget(target)
        wrapper=QWidget();wrapper.setLayout(left)
        v.addWidget(wrapper,3)
        rights=QGroupBox("Rechte")
        rv=QVBoxLayout(rights)
        head=QHBoxLayout()
        head.addWidget(QLabel("Berechtigung"),1)
        head.addWidget(QLabel("Verweigern"))
        head.addWidget(QLabel("Erlauben"))
        rv.addLayout(head)
        self.permission_rows=[]
        for bit,name in PERMISSIONS:
            r=QHBoxLayout()
            r.addWidget(QLabel(name),1)
            deny=QCheckBox()
            grant=QCheckBox()
            deny.toggled.connect(lambda checked,b=bit:self._toggle_permission(b,False,checked))
            grant.toggled.connect(lambda checked,b=bit:self._toggle_permission(b,True,checked))
            r.addWidget(deny);r.addWidget(grant)
            rv.addLayout(r)
            self.permission_rows.append((bit,grant,deny))
        rv.addStretch()
        sc=QScrollArea();sc.setWidgetResizable(True);sc.setWidget(rights)
        v.addWidget(sc,2)
        body.addTab(page,"Berechtigungen")

    def received(self,data):
        super().received(data)
        if self._loaded:
            self._refresh_group_ui()
            self._refresh_rule_ui()

    def _text_at(self,table,row,col):
        return self._text(table,row,col)

    def _refresh_group_ui(self):
        self.group_select.blockSignals(True)
        self.group_select.clear()
        for row in range(self.groups.rowCount()):
            self.group_select.addItem(self._text_at(self.groups,row,0))
        self.group_select.blockSignals(False)
        self.group_select.setCurrentIndex(0 if self.groups.rowCount() else -1)
        self._select_group(self.group_select.currentIndex())

    def _select_group(self,row):
        self._selected_group=row
        if row<0 or row>=self.groups.rowCount():return
        self.groups.selectRow(row)
        for checkbox,col in ((self.group_inherit,3),(self.group_inheritable,4)):
            checkbox.blockSignals(True)
            checkbox.setChecked(self._text_at(self.groups,row,col)=="1")
            checkbox.blockSignals(False)
        for lst,col in self.group_lists:
            lst.clear()
            for text in self._text_at(self.groups,row,col).split(","):
                if text.strip():lst.addItem(text.strip())
        self.inherited_members.clear()
        # Source data supplies inherited member IDs; show them read-only.
        name=self._text_at(self.groups,row,0)
        group=next((g for g in self._source_groups if g["name"]==name),None)
        if group:
            excluded=set(self._ids(self._text_at(self.groups,row,2)))
            for uid in group.get("inherited_members",[]):
                if int(uid) not in excluded:
                    self.inherited_members.addItem(self._user_label(uid))

    def _store_group(self,*_):
        row=self._selected_group
        if not self._loaded or row<0:return
        self._cell(self.groups,row,3,str(int(self.group_inherit.isChecked())))
        self._cell(self.groups,row,4,str(int(self.group_inheritable.isChecked())))

    def _create_group(self):
        if not self._loaded:return
        name,ok=QInputDialog.getText(self,"Mumble-Gruppe","Neue Gruppe:")
        name=name.strip()
        if not ok or not name:return
        if name in [self._text_at(self.groups,r,0) for r in range(self.groups.rowCount())]:
            QMessageBox.warning(self,"Mumble","Diese Gruppe existiert bereits.")
            return
        self._add_row(self.groups)
        row=self.groups.rowCount()-1
        self._cell(self.groups,row,0,name)
        self._refresh_group_ui()
        self.group_select.setCurrentIndex(row)

    def _remove_group(self):
        row=self._selected_group
        if not self._loaded or row<0:return
        self.groups.removeRow(row)
        self._refresh_group_ui()

    def _exclude_inherited_member(self):
        row=self._selected_group
        item=self.inherited_members.currentItem()
        if not self._loaded or row<0 or item is None:return
        uid=self._parse_user_id(item.text())
        excluded=self._ids(self._text_at(self.groups,row,2))
        if uid not in excluded:
            excluded.append(uid)
            self._cell(self.groups,row,2,",".join(self._user_label(v) for v in excluded))
        self._select_group(row)
        self.status.setText("Mitglied für diesen Raum ausgeschlossen. ACL-Änderungen speichern.")

    def _registered_received(self,rows):
        super()._registered_received(rows)
        pending=getattr(self,"_pending_group_column",None)
        if pending is not None and self._registered_rows and self._loaded:
            self._pending_group_column=None
            # Open the picker after this server callback finishes updating the UI.
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0,lambda:self._group_add_user(pending))

    def _group_add_user(self,col):
        row=self._selected_group
        if not self._loaded or row<0:return
        if not self._registered_rows:
            self._pending_group_column=col
            self._request_registered()
            self.status.setText("Registrierte Benutzer werden geladen; die Auswahl öffnet sich automatisch.")
            return
        members=set(self._ids(self._text_at(self.groups,row,1)))
        excluded=set(self._ids(self._text_at(self.groups,row,2)))
        blocked=members|excluded
        candidates=[user for user in self._registered_rows if int(user["user_id"]) not in blocked]
        if not candidates:
            QMessageBox.information(self,"Mumble","Keine weiteren registrierten Benutzer verfügbar.")
            return
        options=[f"{user['name']} (ID {user['user_id']})" for user in candidates]
        choice,ok=QInputDialog.getItem(self,"Mitglied auswählen","Registrierter Benutzer:",options,0,False)
        if not ok:return
        uid=self._parse_user_id(choice)
        if uid in blocked:return
        old=self._ids(self._text_at(self.groups,row,col))
        old.append(uid)
        self._cell(self.groups,row,col,",".join(self._user_label(i) for i in old))
        self._select_group(row)

    def _group_remove_user(self,col,lst):
        row=self._selected_group
        if not self._loaded or row<0 or lst.currentItem() is None:return
        uid=self._parse_user_id(lst.currentItem().text())
        ids=[x for x in self._ids(self._text_at(self.groups,row,col)) if x!=uid]
        self._cell(self.groups,row,col,",".join(self._user_label(i) for i in ids))
        self._select_group(row)

    def _refresh_rule_ui(self,select=0):
        self.rule_list.blockSignals(True)
        self.rule_list.clear()
        for row in range(self.rules.rowCount()):
            group=self._text_at(self.rules,row,0)
            user=self._text_at(self.rules,row,1)
            label=user if user else "@"+group
            if self._text_at(self.rules,row,6)=="1":label+=" (geerbt)"
            self.rule_list.addItem(label)
        self.rule_list.blockSignals(False)
        if self.rules.rowCount():
            self.rule_list.setCurrentRow(min(max(0,select),self.rules.rowCount()-1))
        else:
            self._selected_rule=-1
            self._update_rule_details()

    def _select_rule(self,row):
        self._selected_rule=row
        self._update_rule_details()

    def _update_rule_details(self,*_):
        row=self._selected_rule
        valid=self._loaded and 0<=row<self.rules.rowCount()
        readonly=(not valid or self._text_at(self.rules,row,6)=="1")
        for cb,col in ((self.rule_here,4),(self.rule_subs,5)):
            cb.blockSignals(True)
            cb.setChecked(valid and self._text_at(self.rules,row,col)=="1")
            cb.setEnabled(valid and not readonly)
            cb.blockSignals(False)
        self.rule_target.blockSignals(True)
        self.rule_target.clear()
        for group in ("all","auth","in","out","sub") :
            self.rule_target.addItem("@"+group)
        for n in range(self.groups.rowCount()):
            self.rule_target.addItem("@"+self._text_at(self.groups,n,0))
        if valid:
            uid=self._text_at(self.rules,row,1)
            value=uid if uid else "@"+self._text_at(self.rules,row,0)
            self.rule_target.setCurrentText(value)
        self.rule_target.setEnabled(valid and not readonly)
        self.rule_target.blockSignals(False)
        for bit,grant,deny in self.permission_rows:
            mask_grant=self._mask(row,2) if valid else 0
            mask_deny=self._mask(row,3) if valid else 0
            for cb,checked in ((grant,bool(mask_grant&bit)),(deny,bool(mask_deny&bit))):
                cb.blockSignals(True)
                cb.setChecked(checked)
                cb.setEnabled(valid and not readonly)
                cb.blockSignals(False)

    def _store_rule(self,*_):
        row=self._selected_rule
        if not self._loaded or row<0 or self._text_at(self.rules,row,6)=="1":return
        self._cell(self.rules,row,4,str(int(self.rule_here.isChecked())))
        self._cell(self.rules,row,5,str(int(self.rule_subs.isChecked())))
        value=self.rule_target.currentText().strip()
        if value.startswith("@"):
            self._cell(self.rules,row,0,value[1:])
            self._cell(self.rules,row,1,"")
        elif value:
            try:
                uid=self._parse_user_id(value)
                self._cell(self.rules,row,0,"")
                self._cell(self.rules,row,1,str(uid))
            except ValueError:
                return
        self._refresh_rule_ui(row)

    def _toggle_permission(self,bit,grant,checked):
        row=self._selected_rule
        if not self._loaded or row<0 or self._text_at(self.rules,row,6)=="1":return
        allow=self._mask(row,2)
        deny=self._mask(row,3)
        if grant:
            allow=(allow|bit) if checked else (allow&~bit)
            if checked:deny&=~bit
        else:
            deny=(deny|bit) if checked else (deny&~bit)
            if checked:allow&=~bit
        self._permission_cell(row,2,allow)
        self._permission_cell(row,3,deny)
        self._update_rule_details()

    def _create_rule(self):
        if not self._loaded:return
        self._add_row(self.rules)
        self._refresh_rule_ui(self.rules.rowCount()-1)

    def _remove_rule(self):
        row=self._selected_rule
        if not self._loaded or row<0 or self._text_at(self.rules,row,6)=="1":return
        self.rules.removeRow(row)
        self._refresh_rule_ui(row)

    def _move_rule(self,delta):
        row=self._selected_rule
        dest=row+delta
        if not self._loaded or row<0 or dest<0 or dest>=self.rules.rowCount():return
        if self._text_at(self.rules,row,6)=="1" or self._text_at(self.rules,dest,6)=="1":return
        for col in range(self.rules.columnCount()):
            first=self.rules.takeItem(row,col)
            second=self.rules.takeItem(dest,col)
            self.rules.setItem(row,col,second)
            self.rules.setItem(dest,col,first)
        self._refresh_rule_ui(dest)
