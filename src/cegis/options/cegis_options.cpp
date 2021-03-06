/*******************************************************************\

Module:

Author: Daniel Kroening, kroening@kroening.com

\*******************************************************************/

#include <util/cmdline.h>
#include <util/options.h>
#include <util/mp_arith.h>

#include <cegis/options/cegis_options.h>

cegis_optionst::cegis_optionst(const cmdlinet &cmdline, const optionst &options) :
    cmdline(cmdline), options(options)
{
}

cegis_optionst::~cegis_optionst()
{
}

namespace {
std::string get_option(const cmdlinet &cmdline, const optionst &options,
    const char * const option_name, const char * const default_value)
{
  if (cmdline.isset(option_name)) return cmdline.get_value(option_name);
  const std::string value=options.get_option(option_name);
  if (!value.empty()) return value;
  return default_value;
}
}

std::string cegis_optionst::entry_function_name() const
{
  return get_option(cmdline, options, "function", "main");
}

std::string cegis_optionst::root_function_name() const
{
  return get_option(cmdline, options, "cegis-root", "__CPROVER_synthesis_root");
}

std::list<std::string> cegis_optionst::target_function_names() const
{
  const char option[]="cegis-targets";
  if (cmdline.isset(option)) return cmdline.get_values(option);
  const std::list<std::string> value=options.get_list_option(option);
  if (!value.empty()) return value;
  return std::list<std::string>(1, "__CPROVER_synthesis_learn");
}

std::string cegis_optionst::skolem_function_name() const
{
  return get_option(cmdline, options, "cegis-skolem", "");
}

bool cegis_optionst::has_skolem_function() const
{
  return !skolem_function_name().empty();
}

std::string cegis_optionst::ranking_function_name() const
{
  return get_option(cmdline, options, "cegis-ranking", "");
}

bool cegis_optionst::has_ranking_function() const
{
  return !ranking_function_name().empty();
}

size_t cegis_optionst::max_prog_size() const
{
  const char option[]="cegis-max-prog-size";
  if (cmdline.isset(option))
    return string2integer(cmdline.get_value(option)).to_ulong();
  const size_t value=options.get_unsigned_int_option(option);
  if (value) return value;
  return 10;
}

size_t cegis_optionst::total_target_functions() const
{
  size_t result=target_function_names().size();
  if (has_skolem_function()) ++result;
  if (has_ranking_function()) ++result;
  return result;
}

const optionst &cegis_optionst::get_options() const
{
  return options;
}
