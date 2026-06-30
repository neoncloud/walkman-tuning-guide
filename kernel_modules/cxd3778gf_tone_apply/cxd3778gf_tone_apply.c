/*
 * CXD3778GF tone RAM 手动应用模块。
 *
 * ZX300A 的 stock adjust_tone_control() 在 TYPE_Z 上直接返回，导致写入
 * /proc/icx_audio_cxd3778gf_data/tct 只更新驱动内存，不会刷新 codec tone RAM。
 * 本模块保留 stock 的 tone table 选择逻辑和 MEM_CTRL/MEM_ADDR/MEM_WDAT 写入
 * 序列，但去掉 TYPE_A 限制，并通过 /proc/cxd3778gf_tone_apply 手动触发。
 *
 * 安全边界：
 * - insmod 只解析符号和创建 proc 文件，不自动写寄存器。
 * - 写 "apply" 才会按当前 present 状态选择 table 并刷入 tone RAM。
 * - 写 "table N" 或 "apply N" 可强制刷入指定 table，N 为 0..8。
 * - 不使用 kprobe，不 patch 内核代码。
 */
#define pr_fmt(fmt) "cxd3778gf_tone_apply: " fmt

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/kallsyms.h>
#include <linux/proc_fs.h>
#include <linux/seq_file.h>
#include <linux/uaccess.h>
#include <linux/mutex.h>
#include <linux/string.h>
#include <linux/ctype.h>
#include <sound/cxd3778gf.h>

#define TYPE_A 1
#define TYPE_Z 2

#define CODEC_RAM_WORD_SIZE 5
#define CODEC_RAM_SIZE (CODEC_RAM_WORD_SIZE * 32 * 2)
#define TONE_CONTROL_TABLE_COUNT 9

#define OUTPUT_DEVICE_NONE      0
#define OUTPUT_DEVICE_HEADPHONE 1
#define OUTPUT_DEVICE_LINE      2
#define OUTPUT_DEVICE_SPEAKER   3
#define OUTPUT_DEVICE_FIXEDLINE 4

#define HEADPHONE_AMP_NORMAL      0
#define HEADPHONE_AMP_SMASTER_SE  1
#define HEADPHONE_AMP_SMASTER_BTL 2

#define NCHP_TYPE_NW750N 0
#define NCHP_TYPE_NC31   1
#define NCHP_TYPE_NW500N 2

#define JACK_STATUS_SE_5PIN 3

#define TONE_CONTROL_TABLE_NO_HP            0
#define TONE_CONTROL_TABLE_NAMP_GENERAL_HP  1
#define TONE_CONTROL_TABLE_NAMP_NW500N_NCHP 2
#define TONE_CONTROL_TABLE_NAMP_NW750N_NCHP 3
#define TONE_CONTROL_TABLE_NAMP_NC31_NCHP   4
#define TONE_CONTROL_TABLE_SAMP_GENERAL_HP  5
#define TONE_CONTROL_TABLE_SAMP_NW500N_NCHP 6
#define TONE_CONTROL_TABLE_SAMP_NW750N_NCHP 7
#define TONE_CONTROL_TABLE_SAMP_NC31_NCHP   8

#define CXD3778GF_CLK_HALT 0x17
#define CXD3778GF_CODEC_EN 0x30
#define CXD3778GF_MEM_CTRL 0x70
#define CXD3778GF_MEM_ADDR 0x71
#define CXD3778GF_MEM_WDAT 0x72

typedef int (*reg_write_multiple_fn)(unsigned int address,
				     unsigned char *value,
				     int size);
typedef int (*reg_modify_fn)(unsigned int address,
			     unsigned int value,
			     unsigned int mask);
typedef int (*reg_write_fn)(unsigned int address, unsigned int value);

static struct proc_dir_entry *apply_proc;
static DEFINE_MUTEX(apply_mutex);

static struct cxd3778gf_status *present_ptr;
static unsigned char (*tone_table_ptr)[CODEC_RAM_SIZE];
static reg_write_multiple_fn reg_write_multiple;
static reg_modify_fn reg_modify;
static reg_write_fn reg_write;

static int last_table = -1;
static int last_result;
static unsigned int apply_count;

static const char *table_names[TONE_CONTROL_TABLE_COUNT] = {
	"tct_nh/no_hp",
	"tct_ng/namp_general_hp",
	"tct_nnw500/namp_nw500n_nchp",
	"tct_nnw750/namp_nw750n_nchp",
	"tct_nnc31/namp_nc31_nchp",
	"tct_sg/samp_general_hp",
	"tct_snw500/samp_nw500n_nchp",
	"tct_snw750/samp_nw750n_nchp",
	"tct_snc31/samp_nc31_nchp",
};

static const char *board_type_name(unsigned int value)
{
	switch (value) {
	case TYPE_A:
		return "TYPE_A/a-series";
	case TYPE_Z:
		return "TYPE_Z/zx-series";
	default:
		return "unknown";
	}
}

static int infer_tone_table(const struct cxd3778gf_status *s)
{
	if (s->output_device != OUTPUT_DEVICE_HEADPHONE)
		return TONE_CONTROL_TABLE_NO_HP;

	if (s->jack_status_se == JACK_STATUS_SE_5PIN) {
		if (s->headphone_amp == HEADPHONE_AMP_SMASTER_SE ||
		    s->headphone_amp == HEADPHONE_AMP_SMASTER_BTL) {
			if (s->headphone_type == NCHP_TYPE_NC31)
				return TONE_CONTROL_TABLE_SAMP_NC31_NCHP;
			if (s->headphone_type == NCHP_TYPE_NW500N)
				return TONE_CONTROL_TABLE_SAMP_NW500N_NCHP;
			if (s->headphone_type == NCHP_TYPE_NW750N)
				return TONE_CONTROL_TABLE_SAMP_NW750N_NCHP;
			return TONE_CONTROL_TABLE_SAMP_GENERAL_HP;
		}

		if (s->headphone_type == NCHP_TYPE_NC31)
			return TONE_CONTROL_TABLE_NAMP_NC31_NCHP;
		if (s->headphone_type == NCHP_TYPE_NW500N)
			return TONE_CONTROL_TABLE_NAMP_NW500N_NCHP;
		if (s->headphone_type == NCHP_TYPE_NW750N)
			return TONE_CONTROL_TABLE_NAMP_NW750N_NCHP;
		return TONE_CONTROL_TABLE_NAMP_GENERAL_HP;
	}

	if (s->headphone_amp == HEADPHONE_AMP_SMASTER_SE ||
	    s->headphone_amp == HEADPHONE_AMP_SMASTER_BTL)
		return TONE_CONTROL_TABLE_SAMP_GENERAL_HP;

	return TONE_CONTROL_TABLE_NAMP_GENERAL_HP;
}

static void summarize_table(const unsigned char *buf,
			    unsigned int *sum_out,
			    unsigned int *xor_out,
			    unsigned int *nonzero_out)
{
	unsigned int sum = 0;
	unsigned int xors = 0;
	unsigned int nonzero = 0;
	int i;

	for (i = 0; i < CODEC_RAM_SIZE; i++) {
		sum += buf[i];
		xors ^= (unsigned int)buf[i] << ((i & 3) * 8);
		if (buf[i] != 0)
			nonzero++;
	}

	*sum_out = sum;
	*xor_out = xors;
	*nonzero_out = nonzero;
}

static int cxd3778gf_tone_apply_table(int table)
{
	int rv;
	int n;
	unsigned char *buf;

	if (!tone_table_ptr || !reg_modify || !reg_write || !reg_write_multiple)
		return -ENODEV;
	if (table < 0 || table >= TONE_CONTROL_TABLE_COUNT)
		return -EINVAL;

	buf = tone_table_ptr[table];

	mutex_lock(&apply_mutex);

	/* 以下序列来自 stock adjust_tone_control()，只移除了 TYPE_A gate。 */
	rv = reg_modify(CXD3778GF_CODEC_EN, 0x00, 0x02);
	if (rv < 0)
		goto out;
	rv = reg_modify(CXD3778GF_CLK_HALT, 0x00, 0x08);
	if (rv < 0)
		goto out;
	rv = reg_modify(CXD3778GF_MEM_CTRL, 0x4C, 0xDF);
	if (rv < 0)
		goto out;

	for (n = 0; n < CODEC_RAM_SIZE / (CODEC_RAM_WORD_SIZE * 8); n++) {
		rv = reg_write(CXD3778GF_MEM_ADDR, 8 * n);
		if (rv < 0)
			goto out;
		rv = reg_write_multiple(CXD3778GF_MEM_WDAT,
					buf + CODEC_RAM_WORD_SIZE * 8 * n,
					CODEC_RAM_WORD_SIZE * 8);
		if (rv < 0)
			goto out;
	}

	rv = reg_modify(CXD3778GF_MEM_CTRL, 0x0C, 0xDF);
	if (rv < 0)
		goto out;
	rv = reg_modify(CXD3778GF_CLK_HALT, 0x08, 0x08);
	if (rv < 0)
		goto out;
	rv = reg_modify(CXD3778GF_CODEC_EN, 0x02, 0x02);

out:
	last_table = table;
	last_result = rv;
	if (rv == 0)
		apply_count++;
	mutex_unlock(&apply_mutex);

	if (rv == 0)
		pr_info("applied table=%d(%s)\n", table, table_names[table]);
	else
		pr_err("apply failed table=%d(%s) rv=%d\n",
		       table, table_names[table], rv);
	return rv;
}

static int apply_show(struct seq_file *m, void *v)
{
	struct cxd3778gf_status snapshot;
	int inferred = -1;
	unsigned int sum = 0;
	unsigned int xors = 0;
	unsigned int nonzero = 0;

	seq_printf(m, "ready=%d\n",
		   present_ptr && tone_table_ptr && reg_modify &&
		   reg_write && reg_write_multiple ? 1 : 0);
	seq_printf(m, "present=%p\n", present_ptr);
	seq_printf(m, "tone_table=%p\n", tone_table_ptr);
	seq_printf(m, "reg_modify=%p\n", reg_modify);
	seq_printf(m, "reg_write=%p\n", reg_write);
	seq_printf(m, "reg_write_multiple=%p\n", reg_write_multiple);

	if (present_ptr) {
		memcpy(&snapshot, present_ptr, sizeof(snapshot));
		inferred = infer_tone_table(&snapshot);
		seq_printf(m, "board_type=%u(%s)\n",
			   snapshot.board_type,
			   board_type_name(snapshot.board_type));
		seq_printf(m, "output_device=%d\n", snapshot.output_device);
		seq_printf(m, "headphone_amp=%d\n", snapshot.headphone_amp);
		seq_printf(m, "headphone_type=%d\n", snapshot.headphone_type);
		seq_printf(m, "jack_status_se=%d\n", snapshot.jack_status_se);
		seq_printf(m, "inferred_tone_table=%d(%s)\n",
			   inferred, table_names[inferred]);
	}

	if (tone_table_ptr && inferred >= 0) {
		summarize_table(tone_table_ptr[inferred],
				&sum, &xors, &nonzero);
		seq_printf(m,
			   "inferred_table_summary=sum=0x%08x xor=0x%08x nonzero=%u first16=",
			   sum, xors, nonzero);
		seq_printf(m,
			   "%02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x\n",
			   tone_table_ptr[inferred][0],
			   tone_table_ptr[inferred][1],
			   tone_table_ptr[inferred][2],
			   tone_table_ptr[inferred][3],
			   tone_table_ptr[inferred][4],
			   tone_table_ptr[inferred][5],
			   tone_table_ptr[inferred][6],
			   tone_table_ptr[inferred][7],
			   tone_table_ptr[inferred][8],
			   tone_table_ptr[inferred][9],
			   tone_table_ptr[inferred][10],
			   tone_table_ptr[inferred][11],
			   tone_table_ptr[inferred][12],
			   tone_table_ptr[inferred][13],
			   tone_table_ptr[inferred][14],
			   tone_table_ptr[inferred][15]);
	}

	if (last_table >= 0)
		seq_printf(m, "last_table=%d(%s)\n",
			   last_table, table_names[last_table]);
	else
		seq_printf(m, "last_table=%d\n", last_table);
	seq_printf(m, "last_result=%d\n", last_result);
	seq_printf(m, "apply_count=%u\n", apply_count);
	seq_puts(m, "commands=echo apply > /proc/cxd3778gf_tone_apply; echo table 5 > /proc/cxd3778gf_tone_apply\n");
	return 0;
}

static int apply_open(struct inode *inode, struct file *file)
{
	return single_open(file, apply_show, NULL);
}

static ssize_t apply_write(struct file *file,
			   const char __user *user_buf,
			   size_t count,
			   loff_t *ppos)
{
	char buf[32];
	char *p;
	long table = -1;
	int rv;

	if (count >= sizeof(buf))
		return -EINVAL;
	if (copy_from_user(buf, user_buf, count))
		return -EFAULT;
	buf[count] = '\0';

	p = strim(buf);

	if (!strcmp(p, "apply")) {
		if (!present_ptr)
			return -ENODEV;
		table = infer_tone_table(present_ptr);
	} else if (!strncmp(p, "apply ", 6)) {
		rv = kstrtol(p + 6, 0, &table);
		if (rv < 0)
			return rv;
	} else if (!strncmp(p, "table ", 6)) {
		rv = kstrtol(p + 6, 0, &table);
		if (rv < 0)
			return rv;
	} else {
		return -EINVAL;
	}

	rv = cxd3778gf_tone_apply_table((int)table);
	if (rv < 0)
		return rv;

	return count;
}

static const struct file_operations apply_fops = {
	.owner = THIS_MODULE,
	.open = apply_open,
	.read = seq_read,
	.write = apply_write,
	.llseek = seq_lseek,
	.release = single_release,
};

static int __init cxd3778gf_tone_apply_init(void)
{
	present_ptr = (struct cxd3778gf_status *)kallsyms_lookup_name("present");
	tone_table_ptr = (void *)kallsyms_lookup_name("cxd3778gf_tone_control_table");
	reg_modify = (void *)kallsyms_lookup_name("cxd3778gf_register_modify");
	reg_write = (void *)kallsyms_lookup_name("cxd3778gf_register_write");
	reg_write_multiple =
		(void *)kallsyms_lookup_name("cxd3778gf_register_write_multiple");

	if (!present_ptr || !tone_table_ptr || !reg_modify ||
	    !reg_write || !reg_write_multiple) {
		pr_err("symbol lookup failed present=%p table=%p modify=%p write=%p write_multiple=%p\n",
		       present_ptr, tone_table_ptr, reg_modify,
		       reg_write, reg_write_multiple);
		return -ENOENT;
	}

	apply_proc = proc_create("cxd3778gf_tone_apply", 0644, NULL,
				 &apply_fops);
	if (!apply_proc)
		return -ENOMEM;

	pr_info("loaded present=%p table=%p modify=%p write=%p write_multiple=%p\n",
		present_ptr, tone_table_ptr, reg_modify,
		reg_write, reg_write_multiple);
	return 0;
}

static void __exit cxd3778gf_tone_apply_exit(void)
{
	if (apply_proc)
		remove_proc_entry("cxd3778gf_tone_apply", NULL);
	pr_info("unloaded\n");
}

module_init(cxd3778gf_tone_apply_init);
module_exit(cxd3778gf_tone_apply_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Manual CXD3778GF tone RAM apply helper for TYPE_Z");
MODULE_AUTHOR("zx300-peq-research");
