SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM ((((((((((company_name CROSS JOIN movie_link) CROSS JOIN title) CROSS JOIN movie_companies) CROSS JOIN movie_keyword) CROSS JOIN kind_type) CROSS JOIN cast_info) CROSS JOIN link_type) CROSS JOIN complete_cast) CROSS JOIN keyword) CROSS JOIN role_type) CROSS JOIN movie_info
WHERE company_name.name = 'Sony Pictures Releasing'
  AND cast_info.movie_id = title.id
  AND cast_info.role_id = role_type.id
  AND complete_cast.movie_id = title.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id
  AND title.kind_id = kind_type.id;
