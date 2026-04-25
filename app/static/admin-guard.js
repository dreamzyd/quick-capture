function confirmDeleteGroup(groupName) {
  const typed = window.prompt(`这是高风险操作。\n将删除组「${groupName}」及其全部设备和记录。\n\n如确认删除，请输入组名：`);
  if (typed === null) return false;
  if (typed !== groupName) {
    window.alert('输入的组名不匹配，已取消删除。');
    return false;
  }
  return true;
}
