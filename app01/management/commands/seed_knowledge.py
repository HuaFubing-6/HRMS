r"""
预置制度条目（T3 的"资料"）
==========================

用法：
    .\.venv\Scripts\python.exe manage.py seed_knowledge

设计要点：
    1. 幂等：以 title 为唯一依据 get_or_create，重复执行不会插成双份；
    2. 每条都带 keywords 同义词 —— 用户口语和制度原文往往不是一套词，
       例如问"打卡迟到"，制度标题叫"考勤管理办法"，靠 keywords 才能命中；
    3. 内容是"完整的一段话"，不是碎片：模型拿到完整上下文才不会答半截。
"""
from django.core.management.base import BaseCommand

from app01 import models

KNOWLEDGE_ITEMS = [
    {
        "title": "考勤管理办法",
        "category": "attendance",
        "keywords": "打卡,上下班,迟到,早退,缺勤,迟到扣钱",
        "content": (
            "员工每日上班时间为 9:00，下班时间为 18:00。上班打卡晚于 9:00 记为迟到，"
            "下班打卡早于 18:00 记为早退。迟到一次罚款 50 元，早退一次罚款 50 元，"
            "全天未打卡按缺勤处理，缺勤一天罚款 200 元。罚款在当月薪资中扣除。"
            "一个月内迟到累计超过 3 次的，由部门负责人进行谈话提醒。"
        ),
    },
    {
        "title": "请假管理制度",
        "category": "leave",
        "keywords": "请假,年假,事假,病假,调休,提前申请",
        "content": (
            "请假须提前在系统中提交申请：事假提前 1 个工作日，病假当天可补交并附医院证明，"
            "年假提前 3 个工作日。1 天以内由部门负责人审批，超过 1 天由部门负责人加人力资源部审批。"
            "未审批擅自不到岗按缺勤处理并按考勤办法罚款。年假按入职年限计算，满 1 年 5 天、满 10 年 10 天。"
        ),
    },
    {
        "title": "差旅报销制度",
        "category": "expense",
        "keywords": "出差,报销,住宿,交通,差旅,发票,报销流程",
        "content": (
            "出差前须提交出差申请并获批。住宿标准：一线城市每晚不超过 500 元，其他城市不超过 350 元；"
            "市内交通凭票实报，长途交通按职级标准乘坐。报销时需提交发票原件、出差申请单和行程说明，"
            "在系统「报销」模块提交后由部门负责人与财务双重审核。"
        ),
    },
    {
        "title": "费用报销时限与流程",
        "category": "expense",
        "keywords": "报销时限,多久报销,报销时间,过期,月度报销",
        "content": (
            "费用发生后 30 个自然日内必须提交报销，跨月费用最晚在次月 15 日前提交，"
            "逾期未提交的需附情况说明并由部门负责人签字。每月 20 日为统一付款日，"
            "20 日之后提交的顺延至下月。单笔金额超过 5000 元的报销需财务负责人额外审批。"
        ),
    },
    {
        "title": "加班与调休规定",
        "category": "attendance",
        "keywords": "加班,调休,加班费,周末加班,值班",
        "content": (
            "加班需提前在系统提交加班申请并由部门负责人审批。工作日加班可按 1:1 折算调休，"
            "法定节假日加班按国家规定支付加班费。调休需在加班发生后 3 个月内使用，"
            "逾期作废。调休当天按正常出勤记录考勤。"
        ),
    },
    {
        "title": "薪资发放与结构说明",
        "category": "salary",
        "keywords": "工资,薪资,发工资,几号发,五险一金,绩效,奖金",
        "content": (
            "薪资于每月 15 日发放上月工资，遇节假日提前至最近工作日。"
            "薪资结构为：基本工资 + 绩效奖金 + 补贴 - 个人扣款 - 考勤罚款。"
            "五险一金按当地规定比例由公司与个人分别承担，个人部分在发放前代扣。"
            "工资条可在系统「薪资管理」中查询，对金额有异议应在发放后 5 个工作日内提出复核。"
        ),
    },
    {
        "title": "信息安全与保密要求",
        "category": "security",
        "keywords": "保密,密码,信息安全,数据外发,账号",
        "content": (
            "员工须妥善保管系统账号与密码，密码长度不少于 8 位并包含字母与数字，每 90 天更换一次。"
            "禁止将客户数据、薪酬数据外发或截图分享。离职时须交回全部资料并注销账号。"
            "违反保密要求造成损失的，按公司制度追责。"
        ),
    },
    {
        "title": "入职与转正流程",
        "category": "other",
        "keywords": "入职,转正,试用期,报到,劳动合同",
        "content": (
            "新员工入职当天提交身份证、学历证明与银行卡信息，由人力资源部建立员工档案并分配系统账号。"
            "试用期为 3 个月，试用期满前 10 个工作日提交转正申请，由部门负责人评估后报人力资源部审批。"
            "转正后享受正式员工薪资与年假待遇。"
        ),
    },
]


class Command(BaseCommand):
    help = "写入预置制度条目（T3 制度问答的知识库）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="先删除已有条目再重建（内容改过、想覆盖时用）",
        )

    def handle(self, *args, **options):
        if options["reset"]:
            deleted = models.Knowledge.objects.all().delete()[0]
            self.stdout.write(f"已清空旧条目：{deleted} 条")

        created = 0
        for item in KNOWLEDGE_ITEMS:
            obj, is_new = models.Knowledge.objects.get_or_create(
                title=item["title"],
                defaults={
                    "content": item["content"],
                    "category": item["category"],
                    "keywords": item["keywords"],
                    "is_active": True,
                },
            )
            if is_new:
                created += 1
            elif options["reset"]:
                # reset 时理论上不会走到这里（已清空），留着兜底
                pass

        total = models.Knowledge.objects.filter(is_active=True).count()
        self.stdout.write(self.style.SUCCESS(
            f"新增 {created} 条，当前启用条目共 {total} 条"
        ))
